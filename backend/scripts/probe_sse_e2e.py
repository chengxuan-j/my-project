# -*- coding: utf-8 -*-
"""SSE 流式接口端到端实测（2026-10-16）。

自签一个 access token（无需密码），调 /api/v1/chat/stream，
量出「请求发出 → 首个 delta」与「→ done」的时间，验证流式确实更快。
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

USER_ID = "e_UfToQjT5ido"
MSG = "今天天气挺好的，我出去走了走，顺便买了点菜"
URL = "http://127.0.0.1:8000/api/v1/chat/stream"


async def main():
    token = create_access_token(USER_ID, role="elderly", expires_minutes=5)
    print("已签发测试 token（5 分钟有效）")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    t0 = time.perf_counter()
    first = None
    text = ""
    done_meta = None
    async with httpx.AsyncClient(timeout=120, trust_env=False) as c:
        async with c.stream("POST", URL, json={"message": MSG}, headers=headers) as r:
            print("HTTP", r.status_code, "| content-type:", r.headers.get("content-type"))
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                evt = json.loads(line[5:].strip())
                if evt.get("type") == "delta":
                    if first is None:
                        first = time.perf_counter() - t0
                    text += evt.get("text", "")
                elif evt.get("type") == "done":
                    done_meta = evt
                elif evt.get("type") == "error":
                    print("错误事件:", evt.get("detail"))

    total = time.perf_counter() - t0
    print()
    print("=== 结果 ===")
    print("  首个 delta（首字可见）: %.2fs" % (first or -1))
    print("  全部完成            : %.2fs" % total)
    print("  回复：", text.replace("\n", " ")[:70])
    if done_meta:
        print("  元数据: emotion=%s topic=%s risk=%s action=%s" % (
            done_meta.get("emotion"), done_meta.get("topic"),
            done_meta.get("risk_level"), done_meta.get("action")))


asyncio.run(main())
