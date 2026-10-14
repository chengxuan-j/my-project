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

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",  # 注意：永远不要打印该 header
            "Content-Type": "application/json",
        }

        logger.info("Qwen 请求 model=%s messages=%d", self.model, len(messages))
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
                # 部分模型（如 kimi-k3）不接受 temperature 参数，会返回 400
                # InvalidParameter；去掉该参数重试一次，避免整条链路被一个
                # 无关参数打断（调用方无需关心具体模型支持哪些参数）。
                if resp.status_code == 400 and "temperature" in resp.text:
                    logger.info(
                        "模型 %s 不接受 temperature 参数，去掉后重试",
                        payload.get("model"),
                    )
                    payload.pop("temperature", None)
                    resp = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as e:
            raise LLMError(f"Qwen API 请求超时（{self.timeout}s）") from e
        except (httpx.ConnectError, httpx.ProxyError) as e:
            # 环境里配了代理但代理进程没开（HTTPS_PROXY 指向 127.0.0.1:7897 等）时，
            # 连接会直接失败。DashScope 是阿里云国内服务，直连可达，
            # 这里自动绕过代理重试一次，避免代理开关状态影响 LLM 可用性。
            logger.info("代理连接失败（%s），尝试直连", e)
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout, trust_env=False
                ) as client:
                    resp = await client.post(url, json=payload, headers=headers)
            except httpx.HTTPError as e2:
                raise LLMError(f"Qwen API 网络错误(直连重试也失败): {e2}") from e2
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
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as e:
            raise LLMError(f"Embedding API 请求超时（{self.timeout}s）") from e
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
