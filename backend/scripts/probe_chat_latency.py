# -*- coding: utf-8 -*-
"""对话链路耗时对比（2026-10-16 优化前后）。

用法：直接跑，会打印分析模型、analyze 单步耗时、整轮端到端耗时。
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
ROUNDS = 2


async def main():
    deps = companion_agent._deps
    print("=== 生效模型 ===")
    print("  生成模型 =", deps.client.model)
    print("  分析模型 =", deps.client.analysis_model)
    print()

    print("=== analyze 单步（含是否降级）===")
    for i in range(ROUNDS):
        t = time.perf_counter()
        a = await deps.analyzer.analyze(MSG, recent=[])
        dt = time.perf_counter() - t
        print("  第%d次 %.2fs | degraded=%s emotion=%s topic=%s" % (
            i + 1, dt, getattr(a, "degraded", "?"),
            getattr(a, "emotion", "?"), getattr(a, "topic", "?")))
    print()

    print("=== 整轮端到端（LangGraph: analyze→context→generate）===")
    for i in range(ROUNDS):
        t = time.perf_counter()
        r = await companion_agent.run(USER_ID, MSG)
        dt = time.perf_counter() - t
        print("  第%d次 %.2fs | 回复：%s" % (i + 1, dt, (r.get("reply") or "")[:50]))


asyncio.run(main())
