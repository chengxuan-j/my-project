# -*- coding: utf-8 -*-
"""流式输出的首字/首句延迟实测（2026-10-16）。

非流式 vs 流式的关键差别在"体感首字延迟"：
老人不在意整段生成要 3 秒，在意的是多久看到/听到第一个字。
本探针测：qwen-flash / qwen-plus 在流式模式下的
  - 首 token 到达时间
  - 第一句（到第一个句末标点）完成时间
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


async def stream_stats(model: str) -> None:
    s = get_settings()
    url = f"{s.qwen_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {s.qwen_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": MESSAGES,
        "temperature": 0.8,
        "max_tokens": 200,
        "stream": True,
    }
    t0 = time.perf_counter()
    first_tok = None
    first_sent = None
    buf = ""
    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as r:
            async for line in r.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    delta = json.loads(data)["choices"][0]["delta"]
                except Exception:
                    continue
                piece = delta.get("content") or ""
                if not piece:
                    continue
                if first_tok is None:
                    first_tok = time.perf_counter() - t0
                buf += piece
                if first_sent is None and any(c in piece for c in SENT_END):
                    first_sent = time.perf_counter() - t0
    total = time.perf_counter() - t0
    print("  %-11s 首token %5.2fs | 首句 %5.2fs | 整段 %5.2fs" % (
        model, first_tok or -1, first_sent or total, total))
    print("     内容：", buf.replace("\n", " ")[:60])


async def main():
    print("=== 流式输出延迟（同一 prompt）===")
    for m in ["qwen-flash", "qwen-plus"]:
        try:
            await stream_stats(m)
        except Exception as e:  # noqa: BLE001
            print("  %-11s 异常: %s" % (m, str(e)[:70]))


asyncio.run(main())
