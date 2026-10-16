# -*- coding: utf-8 -*-
"""代理对 LLM 延迟的影响（2026-10-16）。

环境里有 HTTP_PROXY=http://127.0.0.1:7897，而 httpx 默认 trust_env=True
会读取它。DashScope 是阿里云国内服务，本可直连；若被绕进代理会白白加延迟。
本探针对比：走代理 vs 直连（trust_env=False）的首 token 延迟。
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, "E:/elderly_companion/backend")
os.chdir("E:/elderly_companion/backend")

import httpx  # noqa: E402

from app.config import get_settings  # noqa: E402

SENT_END = "。！？!?；;\n"
MESSAGES = [
    {"role": "system", "content": "你是陪伴老人的助手，回复简短亲切，60 字以内。"},
    {"role": "user", "content": "今天天气挺好的，我出去走了走，顺便买了点菜"},
]


async def run(model: str, trust_env: bool, label: str) -> None:
    s = get_settings()
    url = f"{s.qwen_base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {s.qwen_api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": MESSAGES, "temperature": 0.8,
               "max_tokens": 200, "stream": True}
    t0 = time.perf_counter()
    first_tok = None
    try:
        async with httpx.AsyncClient(timeout=60, trust_env=trust_env) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as r:
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        piece = json.loads(data)["choices"][0]["delta"].get("content") or ""
                    except Exception:
                        continue
                    if piece and first_tok is None:
                        first_tok = time.perf_counter() - t0
                        break
        print("  %-8s %-14s 首token %5.2fs" % (model, label, first_tok or -1))
    except Exception as e:  # noqa: BLE001
        print("  %-8s %-14s 失败: %s" % (model, label, str(e)[:60]))


async def main():
    print("=== 代理 vs 直连（同一 prompt、各自跑两次）===")
    for _ in range(2):
        for model in ["qwen-flash"]:
            await run(model, True, "走环境代理")
            await run(model, False, "直连")


asyncio.run(main())
