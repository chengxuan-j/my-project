# -*- coding: utf-8 -*-
"""流式生成首字延迟实测（2026-10-16）。

对比：非流式 run() vs 流式 prepare()+stream_reply()
关心的是"首字延迟"——老人多久能看到/听到第一个字。
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, "E:/elderly_companion/backend")
os.chdir("E:/elderly_companion/backend")

from app.agent import companion_agent  # noqa: E402

USER_ID = "e_UfToQjT5ido"
MSG = "今天天气挺好的，我出去走了走，顺便买了点菜"


async def main():
    print("=== 非流式 run()（整段等完）===")
    t = time.perf_counter()
    r = await companion_agent.run(USER_ID, MSG)
    print("  首字延迟 = 整段耗时 %.2fs" % (time.perf_counter() - t))
    print("  回复：", (r.get("reply") or "")[:60])

    print()
    print("=== 流式 prepare() + stream_reply() ===")
    t0 = time.perf_counter()
    prepared = await companion_agent.prepare(USER_ID, MSG)
    t_prep = time.perf_counter() - t0
    print("  前置（分析+检索）%.2fs" % t_prep)

    t1 = time.perf_counter()
    first = None
    buf = ""
    async for piece in companion_agent.stream_reply(USER_ID, MSG, prepared["context"]):
        if first is None:
            first = time.perf_counter() - t1
        buf += piece
    t_gen = time.perf_counter() - t1
    print("  生成首字 %.2fs | 生成整段 %.2fs" % (first or -1, t_gen))
    print("  端到端首字 %.2fs（前置+首字）" % (t_prep + (first or 0)))
    print("  回复：", buf.replace("\n", " ")[:60])


asyncio.run(main())
