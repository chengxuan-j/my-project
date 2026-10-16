# -*- coding: utf-8 -*-
"""预生成（边说边算）端到端验证（2026-10-16）。

流程：
  1) 用"部分识别文本"调 /chat/speculate（老人还在说话时）
  2) 等预生成跑完
  3) 用"最终文本"调 /chat/stream，量首个 delta 的时间
     —— 命中缓存时应**几乎即时**（跳过分析与生成）

同时对照一组"没有预生成"的请求，看差距。
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, "E:/elderly_companion/backend")
os.chdir("E:/elderly_companion/backend")

import httpx  # noqa: E402

from app.core.security import create_access_token  # noqa: E402

UID = "e_UfToQjT5ido"
BASE = "http://127.0.0.1:8000/api/v1"
PARTIAL = "今天天气挺好的，我出去走了走"
FINAL = "今天天气挺好的，我出去走了走，顺便买了点菜"
COLD = "我昨天晚上睡得还不错，今天精神挺好"


async def call_stream(c: httpx.AsyncClient, headers: dict, message: str):
    t0 = time.perf_counter()
    first = None
    text = ""
    async with c.stream("POST", f"{BASE}/chat/stream",
                        json={"message": message}, headers=headers) as r:
        async for line in r.aiter_lines():
            if not line.startswith("data:"):
                continue
            evt = json.loads(line[5:].strip())
            if evt.get("type") == "delta":
                if first is None:
                    first = time.perf_counter() - t0
                text += evt.get("text", "")
            elif evt.get("type") == "error":
                print("   错误:", evt.get("detail"))
    return first, time.perf_counter() - t0, text


async def main():
    token = create_access_token(UID, role="elderly", expires_minutes=10)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=120, trust_env=False) as c:
        print("=== 对照组：无预生成 ===")
        f, t, txt = await call_stream(c, headers, COLD)
        print("  首个 delta %.2fs | 全部 %.2fs | %s" % (f, t, txt[:40]))

        print()
        print("=== 预生成组 ===")
        r = await c.post(f"{BASE}/chat/speculate",
                         json={"message": PARTIAL}, headers=headers)
        print("  /chat/speculate ->", r.status_code, r.text[:60])
        # 给预生成留出跑完的时间（真实场景里这几秒老人还在说话）
        await asyncio.sleep(6)

        f, t, txt = await call_stream(c, headers, FINAL)
        print("  首个 delta %.2fs | 全部 %.2fs | %s" % (f, t, txt[:40]))
        print()
        print("  说明：命中时首个 delta 应接近 0.1s 量级（跳过分析与生成）")


asyncio.run(main())
