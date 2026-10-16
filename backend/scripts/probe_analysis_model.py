# -*- coding: utf-8 -*-
"""对比不同分析模型对首字延迟的影响（2026-10-16）。

analyze 是分类任务（情绪/意图/话题/场景），不需要推理模型。
逐个模型跑同一句话，看耗时 + 是否返回有效 JSON。
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, "E:/elderly_companion/backend")
os.chdir("E:/elderly_companion/backend")

from app.agent import companion_agent  # noqa: E402

MSG = "今天天气挺好的，我出去走了走，顺便买了点菜"
CANDIDATES = ["kimi-k3", "qwen-plus", "qwen-turbo", "qwen-flash"]


async def main():
    deps = companion_agent._deps
    orig = deps.client.analysis_model
    print("=== 分析环节：不同模型对比（同一句话）===")
    for m in CANDIDATES:
        deps.client.analysis_model = m
        t = time.perf_counter()
        try:
            a = await deps.analyzer.analyze(MSG, recent=[])
            dt = time.perf_counter() - t
            ok = not getattr(a, "degraded", False)
            print("  %-11s %6.2fs  有效JSON=%-5s emotion=%-8s topic=%s" % (
                m, dt, ok, getattr(a, "emotion", "?"), getattr(a, "topic", "?")))
        except Exception as e:  # noqa: BLE001
            dt = time.perf_counter() - t
            print("  %-11s %6.2fs  异常: %s" % (m, dt, str(e)[:60]))
    deps.client.analysis_model = orig


asyncio.run(main())
