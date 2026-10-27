"""语音能力：TTS 合成 + ASR 识别（全部走 DashScope 远程 API，零本地模型）。

- TTS：POST /api/v1/services/audio/tts/SpeechSynthesizer，非流式，返回音频 URL（24h）
- ASR：三步 —— ① 上传音频拿临时 oss URL ② 提交转写任务 ③ 轮询结果

异步化：所有方法改 async，httpx.AsyncClient，time.sleep 改 asyncio.sleep。
ASR 已拆出 upload_audio / submit_transcription / poll_result 三个公开方法，
便于路由层实现「提交即返回 task_id + GET 轮询」的异步端点。
"""
import asyncio
import json
import logging
import os
import uuid
from typing import Any, Dict, Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

TTS_ENDPOINT = "/api/v1/services/audio/tts/SpeechSynthesizer"
# 方言音色走多模态生成接口（qwen3-tts 系列），和上面那个老接口不是同一个地址
TTS_DIALECT_ENDPOINT = "/api/v1/services/aigc/multimodal-generation/generation"
ASR_ENDPOINT = "/api/v1/services/audio/asr/transcription"
UPLOAD_ENDPOINT = "/api/v1/uploads"
TASKS_ENDPOINT = "/api/v1/tasks"

# 老人陪伴场景的默认音色：温暖女声
DEFAULT_VOICE = "longanhuan_v3.6"
TTS_MODEL = "qwen-audio-3.0-tts-flash"
ASR_MODEL = "paraformer-v2"

# ASR 单次轮询状态
ASR_PENDING = "PENDING"
ASR_RUNNING = "RUNNING"
ASR_SUCCEEDED = "SUCCEEDED"
ASR_FAILED = "FAILED"
ASR_CANCELED = "CANCELED"
ASR_NO_VALID_FRAGMENT = "SUCCESS_WITH_NO_VALID_FRAGMENT"


class SpeechError(Exception):
    """语音相关错误。"""


class SpeechClient:
    """TTS + ASR 统一封装（异步）。"""

    def __init__(self) -> None:
        s = get_settings()
        self.api_key = s.qwen_api_key
        self.base_url = s.qwen_base_url.rstrip("/")
        self.timeout = s.request_timeout
        # 语音接口实际都在 dashscope.aliyuncs.com 根域下（非 compatible-mode 前缀）
        self.speech_base = "https://dashscope.aliyuncs.com"
        self._http: Optional[httpx.AsyncClient] = None
        # 语音模型可配置：fun-asr 才支持方言，paraformer-v2 只做普通话兜底
        self.asr_model = s.asr_model or ASR_MODEL
        self.asr_fallback_model = s.asr_fallback_model or "paraformer-v2"
        self.tts_model = s.tts_model or TTS_MODEL
        # 方言音色只能配 qwen3-tts 系列，不能和上面的 tts_model 混用
        self.tts_dialect_model = s.tts_dialect_model or "qwen3-tts-flash"
        self.tts_voice = s.tts_voice or DEFAULT_VOICE

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _client(self) -> httpx.AsyncClient:
        """复用持久连接，并**直连** DashScope / OSS。

        httpx 默认 trust_env=True 会读取环境里的 HTTP_PROXY，
        把本可直连的国内请求绕进代理（实测每次多 0.7~1.2s）。
        """
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=self.timeout, trust_env=False)
        return self._http

    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        h = {"Authorization": f"Bearer {self.api_key}"}
        if extra:
            h.update(extra)
        return h

    # ---------------- TTS ----------------

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        instruction: Optional[str] = None,
    ) -> str:
        """文字转语音（普通话音色），返回音频 URL。

        instruction 用自然语言控制语气，但**实测对模型无效**：
        传「请用英文说这句」出来的仍然是中文，所以不要再指望它切方言，
        方言请走 synthesize_dialect（靠专用音色）。
        """
        if not self.api_key:
            raise SpeechError("未配置 QWEN_API_KEY，无法调用语音合成。")
        url = f"{self.speech_base}{TTS_ENDPOINT}"
        input_payload: Dict[str, Any] = {
            "text": text,
            "voice": voice or self.tts_voice,
            "format": "mp3",
        }
        if instruction:
            input_payload["instruction"] = instruction
        payload = {
            "model": self.tts_model,
            "input": input_payload,
        }
        try:
            resp = await self._client().post(
                url, json=payload, headers=self._headers()
            )
        except httpx.HTTPError as e:
            raise SpeechError(f"TTS 网络错误: {e}") from e

        if resp.status_code != 200:
            raise SpeechError(f"TTS 返回 HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            audio_url = resp.json()["output"]["audio"]["url"]
        except (json.JSONDecodeError, KeyError) as e:
            raise SpeechError(f"TTS 响应结构异常: {resp.text[:200]}") from e
        logger.info(
            "TTS 合成成功（%d 字，dialect_instruction=%s）",
            len(text), bool(instruction),
        )
        return audio_url

    async def synthesize_dialect(self, text: str, voice: str) -> str:
        """用**方言专用音色**合成，返回音频 URL。

        qwen3-tts 的方言靠音色而不是指令：Sunny/Eric=四川，Kiki/Rocky=粤语，
        Jada=上海，Marcus=陕西…（见 app/companion/dialects.py 的映射）。
        这条走的是多模态生成接口，和老接口不是同一个 URL。
        """
        if not self.api_key:
            raise SpeechError("未配置 QWEN_API_KEY，无法调用语音合成。")
        payload = {
            "model": self.tts_dialect_model,
            "input": {"text": text, "voice": voice},
        }
        try:
            resp = await self._client().post(
                f"{self.speech_base}{TTS_DIALECT_ENDPOINT}",
                json=payload,
                headers=self._headers(),
            )
        except httpx.HTTPError as e:
            raise SpeechError(f"方言 TTS 网络错误: {e}") from e
        if resp.status_code != 200:
            raise SpeechError(
                f"方言 TTS 返回 HTTP {resp.status_code}: {resp.text[:200]}"
            )
        try:
            audio_url = resp.json()["output"]["audio"]["url"]
        except (json.JSONDecodeError, KeyError) as e:
            raise SpeechError(f"方言 TTS 响应结构异常: {resp.text[:200]}") from e
        logger.info("方言 TTS 合成成功（%d 字，voice=%s）", len(text), voice)
        return audio_url

    # ---------------- ASR ----------------

    async def upload_audio(
        self, audio_bytes: bytes, filename: str, model: Optional[str] = None
    ) -> str:
        """上传音频到 DashScope 临时 OSS，返回 oss:// URL。

        OSS key 的后缀会被服务端用于判断音频格式，必须与 filename 真实后缀一致，
        不能写死成 .wav（否则 webm 会被当成 wav 解析而失败）。
        model 省略时用默认 ASR 模型；普通话可传 paraformer-v2 更快。
        """
        asr_model = model or self.asr_model
        suffix = os.path.splitext(filename or "")[1].lower()
        if suffix not in (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus"):
            suffix = ".wav"
        mime = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac",
                ".flac": "audio/flac", ".ogg": "audio/ogg",
                ".opus": "audio/ogg"}.get(suffix, "audio/wav")

        client = self._client()
        # 1) 取上传策略
        r = await client.get(
            f"{self.speech_base}{UPLOAD_ENDPOINT}",
            headers=self._headers(),
            params={"action": "getPolicy", "model": asr_model},
        )
        if r.status_code != 200 and asr_model != self.asr_fallback_model:
            logger.warning(
                "取上传策略失败（model=%s），回退 %s 重试: HTTP %s",
                asr_model, self.asr_fallback_model, r.status_code,
            )
            r = await client.get(
                f"{self.speech_base}{UPLOAD_ENDPOINT}",
                headers=self._headers(),
                params={"action": "getPolicy", "model": self.asr_fallback_model},
            )
        if r.status_code != 200:
            raise SpeechError(
                f"取上传策略失败: HTTP {r.status_code} {r.text[:200]}"
            )
        policy = r.json()["data"]

        # 2) 直传 OSS
        key = f"{policy['upload_dir']}/{uuid.uuid4().hex}{suffix}"
        files = {
            "OSSAccessKeyId": (None, policy["oss_access_key_id"]),
            "Signature": (None, policy["signature"]),
            "policy": (None, policy["policy"]),
            "x-oss-object-acl": (None, policy["x_oss_object_acl"]),
            "x-oss-forbid-overwrite": (None, policy["x_oss_forbid_overwrite"]),
            "key": (None, key),
            "success_action_status": (None, "200"),
            "file": (f"audio{suffix}", audio_bytes, mime),
        }
        up = await client.post(policy["upload_host"], files=files)
        if up.status_code != 200:
            raise SpeechError(
                f"上传音频失败: HTTP {up.status_code} {up.text[:200]}"
            )
        return f"oss://{key}"

    async def submit_transcription(
        self, oss_url: str, model: Optional[str] = None
    ) -> str:
        """提交 ASR 转写任务，立即返回 task_id（非阻塞）。

        默认用 fun-asr：它原生支持官话/吴/湘/赣/客/闽/粤七大方言，
        老人说四川话、粤语、上海话都能转写，不需要前端指定方言。
        普通话（未开方言）可传 paraformer-v2，速度更快、价格更低。
        模型不可用时回退 paraformer-v2，保证基本可用。
        """
        primary = model or self.asr_model
        async def _submit(model: str) -> httpx.Response:
            payload: Dict[str, Any] = {
                "model": model,
                "input": {"file_urls": [oss_url]},
            }
            # paraformer 才需要语言提示；fun-asr 传空参数让它自动判方言
            if not model.startswith("fun-asr"):
                payload["parameters"] = {"language_hints": ["zh"]}
            return await self._client().post(
                f"{self.speech_base}{ASR_ENDPOINT}",
                json=payload,
                headers=self._headers({"X-DashScope-Async": "enable",
                                       "X-DashScope-OssResourceResolve": "enable"}),
            )

        r = await _submit(primary)
        if r.status_code == 400 and primary != self.asr_fallback_model:
            code = ""
            try:
                body = r.json()
                code = str(body.get("code") or (body.get("error") or {}).get("code") or "")
            except Exception:  # noqa: BLE001
                pass
            if code in ("InvalidParameter", "ModelNotFound", "UnsupportedModel"):
                logger.warning("ASR 模型 %s 不可用，回退 %s", primary,
                               self.asr_fallback_model)
                r = await _submit(self.asr_fallback_model)
        if r.status_code != 200:
            raise SpeechError(f"提交转写失败: HTTP {r.status_code} {r.text[:200]}")
        return r.json()["output"]["task_id"]

    async def fetch_result(self, task_id: str) -> Dict[str, Any]:
        """查一次转写任务状态（非阻塞轮询）。

        返回 {"status": ..., "text": Optional[str], "error": Optional[str]}
        - status in {PENDING, RUNNING, SUCCEEDED, FAILED, CANCELED}
        - text 仅在 SUCCEEDED 时非空
        - error 仅在失败时非空
        """
        url = f"{self.speech_base}{TASKS_ENDPOINT}/{task_id}"
        r = await self._client().get(
            url, headers=self._headers({"X-DashScope-Async": "enable"}),
        )
        if r.status_code != 200:
            raise SpeechError(f"查询转写任务失败: HTTP {r.status_code}")
        out = r.json().get("output", {})
        status = out.get("task_status", ASR_PENDING)

        if status == ASR_SUCCEEDED:
            # 结果在 results[0].transcription_url 指向的 JSON 里
            try:
                trans_url = out["results"][0]["transcription_url"]
                tr = await self._client().get(trans_url)
                data = tr.json()
                texts = [t["text"] for t in data.get("transcripts", [])]
                return {"status": status, "text": "".join(texts).strip(),
                        "error": None}
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                return {"status": ASR_FAILED, "text": None,
                        "error": f"解析转写结果失败: {e}"}

        if status in (ASR_FAILED, ASR_CANCELED):
            code = out.get("code", "")
            # 任务跑了但没识别出有效片段 → 通常是录音静音/太短/编码问题
            if code == ASR_NO_VALID_FRAGMENT:
                return {"status": status, "text": None,
                        "error": "未识别到有效语音（录音可能静音、太短或音频格式有误）"}
            return {"status": status, "text": None,
                    "error": f"转写任务失败: code={code}"}

        return {"status": status, "text": None, "error": None}

    async def poll_result(self, task_id: str, max_wait: float = 120.0,
                          interval: float = 1.0) -> str:
        """阻塞式轮询：直到 SUCCEEDED 或失败/超时，返回文本。

        主要给同步路径/老接口 transcribe 使用；新路由请改用 fetch_result 做轮询。
        """
        deadline = asyncio.get_event_loop().time() + max_wait
        while asyncio.get_event_loop().time() < deadline:
            res = await self.fetch_result(task_id)
            status = res["status"]
            if status == ASR_SUCCEEDED:
                return res["text"] or ""
            if status in (ASR_FAILED, ASR_CANCELED):
                raise SpeechError(res["error"] or "转写任务失败")
            await asyncio.sleep(interval)
        raise SpeechError(f"转写任务超时（>{max_wait}s）")

    async def transcribe(self, audio_bytes: bytes,
                         filename: str = "audio.wav") -> str:
        """音频转文字（一键完整流程：上传 → 提交 → 轮询）。"""
        if not self.api_key:
            raise SpeechError("未配置 QWEN_API_KEY，无法调用语音识别。")
        if len(audio_bytes) < 1024:
            raise SpeechError("录音太短（<1KB），可能没录到声音，请按住说话时长一点再松手")
        logger.info("ASR 收到音频: %d 字节, filename=%s", len(audio_bytes), filename)
        oss_url = await self.upload_audio(audio_bytes, filename)
        task_id = await self.submit_transcription(oss_url)
        logger.info("ASR 任务已提交 task_id=%s", task_id)
        text = await self.poll_result(task_id)
        logger.info("ASR 识别完成: %s", text[:40])
        return text


_client = SpeechClient()
