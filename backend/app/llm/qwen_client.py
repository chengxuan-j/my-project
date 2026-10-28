"""Qwen API 统一封装。

- LLMClient 抽象接口：后续换其他厂商 API 只需新增子类
- QwenClient：通过 OpenAI 兼容端点（DashScope）真实调用通义千问
- 有网络错误 / 超时 / API 异常处理，日志中绝不输出 API Key

注：方法全为 async，配合 FastAPI 异步路由使用；底层 httpx.AsyncClient。
"""
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """LLM 调用相关错误（网络 / 超时 / API 返回异常 / 响应结构异常）。"""


class LLMClient(ABC):
    """统一 LLM 接口（异步）。"""

    @abstractmethod
    async def chat(self, messages: List[Dict[str, str]], **kwargs: Any) -> str:
        """输入 OpenAI 格式 messages，返回回复文本。"""

    async def embed(self, texts: List[str]) -> List[List[float]]:
        """默认实现：抛 NotImplementedError，子类按需覆写。"""
        raise NotImplementedError


class QwenClient(LLMClient):
    """通过 HTTP 调用 Qwen API（DashScope OpenAI 兼容模式）。"""

    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.qwen_api_key
        self.base_url = settings.qwen_base_url
        self.model = settings.qwen_model
        # 情境分析等轻量任务用快模型，省一半耗时
        self.analysis_model = settings.qwen_analysis_model
        self.timeout = settings.request_timeout
        # 推理模型是否下发 enable_thinking：None 表示不传（保持服务端默认）
        self.enable_thinking = settings.qwen_enable_thinking
        # 持久 HTTP 连接池：复用同一个 AsyncClient，避免每次请求重建 TCP+TLS。
        # 一轮对话有 3 次调用（情境分析 / 向量检索 / 生成回复），累计可省 0.5~1s。
        self._clients: Dict[bool, httpx.AsyncClient] = {}

    def _client(self, trust_env: bool = True) -> httpx.AsyncClient:
        """按 trust_env 复用 httpx.AsyncClient。

        默认调用方应传 trust_env=False（直连 DashScope，避免被环境代理拖慢）；
        trust_env=True 仅在直连失败时作为回退使用。
        """
        c = self._clients.get(trust_env)
        if c is None or c.is_closed:
            c = httpx.AsyncClient(timeout=self.timeout, trust_env=trust_env)
            self._clients[trust_env] = c
        return c

    def _apply_thinking(self, payload: Dict[str, Any], kwargs: Dict[str, Any]) -> None:
        """按配置决定是否下发 enable_thinking。

        推理模型（qwen3 系列）默认先输出思维链，content 要等思考完才出来，
        陪伴场景下这 7 秒的差距不能接受。调用方可用 kwargs 单独覆盖。
        """
        thinking = kwargs.get("enable_thinking", self.enable_thinking)
        if thinking is not None:
            payload["enable_thinking"] = bool(thinking)

    @property
    def is_configured(self) -> bool:
        """是否配置了 API Key（供启动时自检，避免请求时报错难定位）。"""
        return bool(self.api_key)

    async def chat(self, messages: List[Dict[str, str]], **kwargs: Any) -> str:
        if not self.api_key:
            raise LLMError("未配置 QWEN_API_KEY，请在 .env 中填写后重启服务。")

        payload: Dict[str, Any] = {
            "model": kwargs.get("model") or self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.8),
        }
        if "max_tokens" in kwargs:
            payload["max_tokens"] = kwargs["max_tokens"]
        self._apply_thinking(payload, kwargs)

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",  # 注意：永远不要打印该 header
            "Content-Type": "application/json",
        }

        logger.info("Qwen 请求 model=%s messages=%d", self.model, len(messages))
        try:
            # 直连优先：DashScope 是阿里云国内服务，直连可达。
            # 环境里若配了 HTTP_PROXY（如本机 127.0.0.1:7897），httpx 默认
            # trust_env=True 会把国内请求也绕进代理，实测每次多 0.7~1.2s。
            client = self._client(trust_env=False)
            resp = await client.post(url, json=payload, headers=headers)
            # 部分模型不接受某些可选参数（如 kimi-k3 不认 temperature、
            # 老模型不认 enable_thinking），逐个摘掉重试一次，避免一个
            # 无关参数打断整条链路（调用方无需关心具体模型支持哪些参数）。
            for opt in ("temperature", "enable_thinking"):
                if resp.status_code != 400 or opt not in payload or opt not in resp.text:
                    break
                logger.info(
                    "模型 %s 不接受 %s 参数，去掉后重试",
                    payload.get("model"),
                    opt,
                )
                payload.pop(opt, None)
                resp = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as e:
            raise LLMError(f"Qwen API 请求超时（{self.timeout}s）") from e
        except (httpx.ConnectError, httpx.ProxyError) as e:
            # 直连不通时（个别网络环境必须走代理），回退到读取环境代理重试一次。
            logger.info("DashScope 直连失败（%s），回退走环境代理", e)
            try:
                resp = await self._client(trust_env=True).post(
                    url, json=payload, headers=headers
                )
            except httpx.HTTPError as e2:
                raise LLMError(f"Qwen API 网络错误(直连与代理均失败): {e2}") from e2
        except httpx.HTTPError as e:
            raise LLMError(f"Qwen API 网络错误: {e}") from e

        if resp.status_code != 200:
            # 不回显 Authorization；DashScope 错误体里也不含 Key
            raise LLMError(
                f"Qwen API 返回 HTTP {resp.status_code}: {resp.text[:300]}"
            )

        try:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            raise LLMError(f"Qwen API 响应结构异常: {str(resp.text)[:200]}") from e

        usage = data.get("usage") or {}
        logger.info(
            "Qwen 回复成功 tokens=(prompt=%s completion=%s)",
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
        )
        return content

    async def chat_stream(self, messages: List[Dict[str, str]], **kwargs: Any):
        """流式生成：逐段 yield 内容增量（用于 SSE 等"边收边渲染/边播"场景）。

        与 chat() 相同的直连优先策略；直连建连失败时回退环境代理。
        首个 token 就产出，调用方无需等整段生成完。
        """
        if not self.api_key:
            raise LLMError("未配置 QWEN_API_KEY，请在 .env 中填写后重启服务。")

        payload: Dict[str, Any] = {
            "model": kwargs.get("model") or self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.8),
            "stream": True,
        }
        if "max_tokens" in kwargs:
            payload["max_tokens"] = kwargs["max_tokens"]
        self._apply_thinking(payload, kwargs)

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async def _iter(trust_env: bool):
            client = self._client(trust_env=trust_env)
            async with client.stream(
                "POST", url, json=payload, headers=headers
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise LLMError(
                        f"Qwen API 返回 HTTP {resp.status_code}: {body[:300]!r}"
                    )
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        delta = json.loads(data)["choices"][0].get("delta") or {}
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    piece = delta.get("content")
                    if piece:
                        yield piece

        started = False
        try:
            async for piece in _iter(trust_env=False):
                started = True
                yield piece
        except httpx.TimeoutException as e:
            raise LLMError(f"Qwen 流式请求超时（{self.timeout}s）") from e
        except (httpx.ConnectError, httpx.ProxyError) as e:
            if started:
                # 已经吐过内容，无法重新开始，直接报错让上层处理
                raise LLMError(f"Qwen 流式中断: {e}") from e
            logger.info("DashScope 直连失败（%s），回退走环境代理", e)
            async for piece in _iter(trust_env=True):
                yield piece
        except httpx.HTTPError as e:
            raise LLMError(f"Qwen 流式网络错误: {e}") from e

    async def embed(self, texts: List[str]) -> List[List[float]]:
        """调用 DashScope embedding API（text-embedding-v3），返回向量列表。

        用于长期记忆语义检索。同一套错误处理风格，失败抛 LLMError。
        """
        if not self.api_key:
            raise LLMError("未配置 QWEN_API_KEY，请在 .env 中填写后重启服务。")

        model = get_settings().embedding_model

        url = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": model, "input": texts}

        try:
            # 同 chat：DashScope 直连优先，避免被环境代理拖慢
            resp = await self._client(trust_env=False).post(
                url, json=payload, headers=headers
            )
        except httpx.TimeoutException as e:
            raise LLMError(f"Embedding API 请求超时（{self.timeout}s）") from e
        except (httpx.ConnectError, httpx.ProxyError) as e:
            logger.info("Embedding 直连失败（%s），回退走环境代理", e)
            try:
                resp = await self._client(trust_env=True).post(
                    url, json=payload, headers=headers
                )
            except httpx.HTTPError as e2:
                raise LLMError(f"Embedding API 网络错误(直连与代理均失败): {e2}") from e2
        except httpx.HTTPError as e:
            raise LLMError(f"Embedding API 网络错误: {e}") from e

        if resp.status_code != 200:
            raise LLMError(
                f"Embedding API 返回 HTTP {resp.status_code}: {resp.text[:300]}"
            )

        try:
            data = resp.json()
            items = sorted(data["data"], key=lambda x: x["index"])
            return [it["embedding"] for it in items]
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            raise LLMError(f"Embedding API 响应结构异常: {str(resp.text)[:200]}") from e
