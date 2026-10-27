"""Qwen-VL 图像理解：视觉服务不可用时的云端兜底。

使用 OpenAI 兼容端点，图片以 base64 data URI 传入。
- 小智视觉服务（:8003）没启动时，`/vision/describe` 走这里；
- 本地 DeepFace 缺 cv2/torch 时，`/emotion/face` 走这里做表情分类。
"""
from __future__ import annotations

import base64
import logging

import httpx

from app.config import get_settings
from app.llm.qwen_client import LLMError

logger = logging.getLogger(__name__)


async def describe_image(
    image_bytes: bytes,
    prompt: str,
    mime: str = "image/jpeg",
    max_tokens: int = 400,
) -> str:
    """把图片 + 提示词发给 Qwen-VL，返回纯文本。"""
    s = get_settings()
    if not s.qwen_api_key:
        raise LLMError("未配置 QWEN_API_KEY，无法调用视觉模型")

    b64 = base64.b64encode(image_bytes).decode()
    payload = {
        "model": s.qwen_vision_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "max_tokens": max_tokens,
    }
    url = f"{s.qwen_base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {s.qwen_api_key}"}

    try:
        async with httpx.AsyncClient(timeout=s.request_timeout, trust_env=False) as c:
            resp = await c.post(url, json=payload, headers=headers)
    except httpx.HTTPError as e:
        raise LLMError(f"视觉模型网络错误: {e}") from e

    if resp.status_code != 200:
        raise LLMError(
            f"视觉模型返回 HTTP {resp.status_code}: {resp.text[:200]}"
        )
    try:
        content = resp.json()["choices"][0]["message"].get("content") or ""
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise LLMError(f"视觉模型响应结构异常: {resp.text[:200]}") from e
    text = content.strip()
    logger.info("Qwen-VL 返回（%d 字，model=%s）", len(text), s.qwen_vision_model)
    return text
