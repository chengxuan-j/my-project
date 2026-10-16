# -*- coding: utf-8 -*-
"""前置阶段（analyze + 检索）耗时拆解（2026-10-16）。

流式改造后首个 delta 仍要 ~2.7s，说明瓶颈在"生成之前"。
本探针把前置拆开，找出到底哪一段在吃时间。
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
    deps = companion_agent._deps

    # 1) 分析（带真实近期历史，贴近线上条件）
    history = deps.memory.short.recent_messages(USER_ID)
    print("近期历史条数:", len(history))
    t = time.perf_counter()
    a = await deps.analyzer.analyze(MSG, recent=history)
    t_analyze = time.perf_counter() - t
    print("  ① analyze（带历史）        %5.2fs" % t_analyze)

    # 2) 向量检索（embedding）
    t = time.perf_counter()
    mems = await deps.memory.long.search_multi(USER_ID, [MSG])
    t_embed = time.perf_counter() - t
    print("  ② 长期记忆检索（含embedding）%5.2fs | 命中 %d 条" % (t_embed, len(mems)))

    # 3) 知识库检索
    t = time.perf_counter()
    try:
        kn = await deps.memory.knowledge.search(MSG, user_id=USER_ID, top_k=4)
    except Exception as e:  # noqa: BLE001
        kn = []
        print("    知识库检索异常:", str(e)[:60])
    t_kn = time.perf_counter() - t
    print("  ③ 知识库检索               %5.2fs | 命中 %d 条" % (t_kn, len(kn)))

    # 4) 完整 build_context（对照）
    t = time.perf_counter()
    await deps.memory.build_context(USER_ID, MSG, analysis=a)
    t_ctx = time.perf_counter() - t
    print("  ④ build_context 合计        %5.2fs" % t_ctx)

    print()
    print("=== 若把 ①②③ 并发，理论前置 = max(三者) ≈ %.2fs（现串行 %.2fs）===" % (
        max(t_analyze, t_embed, t_kn), t_analyze + t_embed + t_kn))


asyncio.run(main())
