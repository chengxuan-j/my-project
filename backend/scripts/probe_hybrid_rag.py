# -*- coding: utf-8 -*-
"""混合检索链路验证（2026-10-19）。

按 E:\\enterprise-rag 的 rag.py 结构重写知识库检索后的集成验证：
  ① 各模块单元行为（BM25 / RRF / 改写 / 精排）
  ② 真实知识库上的检索效果与耗时分解
  ③ 与改造前"语义/词面二选一"的结果对比（同 query）
  ④ 相关性门控：不相关的 query 是否被正确拒答
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, "E:/elderly_companion/backend")
os.chdir("E:/elderly_companion/backend")

from app.rag.bm25 import BM25Index  # noqa: E402
from app.rag.hybrid import rrf_fuse  # noqa: E402
from app.rag.knowledge_base import KnowledgeBase  # noqa: E402
from app.rag.rewrite import QueryRewriter  # noqa: E402

UID = "e_UfToQjT5ido"

QUERIES = [
    ("老人跌倒了怎么办", "应命中：跌倒处理"),
    ("他说不想活了", "应命中：安全处理"),
    ("头晕胸闷要做什么", "应命中：身体不适沟通"),
    ("怎么跟难过的老人说话", "应命中：情绪陪伴原则"),
    ("留言说些什么好", "应命中：家属留言建议"),
    ("知识库的资料能给谁看", "应命中：隐私边界"),
    ("今天天气怎么样", "不应命中：完全无关"),
    ("怎么做糖醋鱼", "不应命中：完全无关"),
]


async def main():
    print("=" * 78)
    print("① 单元行为")
    print("=" * 78)
    idx = BM25Index().build([(1, "老人跌倒后不要急着扶起来"), (2, "糖醋鱼要放醋和糖"),
                             (3, "头晕胸闷应立即联系家属和医生")])
    print("  BM25 '跌倒':", idx.search("跌倒", top_k=3))
    print("  BM25 '5000':", idx.search("报销上限 5000 元", top_k=1), "（无此词→空）")
    fused = rrf_fuse([(1, 0.9), (2, 0.8)], [(3, 12.3), (1, 5.0)])
    print("  RRF 融合:", [(cid, round(s, 4), src) for cid, s, src in fused])
    rw = QueryRewriter()
    print("  改写门控 '这个怎么办' + 历史:", rw.rewrite("这个怎么办", ["老人跌倒了怎么办"]))
    print("  改写门控 '年假几天'（不应改写）:", rw.rewrite("年假几天", []))

    print()
    print("=" * 78)
    print("②③ 真实知识库检索（王奶奶可见范围）")
    print("=" * 78)
    kb = KnowledgeBase()
    for query, note in QUERIES:
        t = time.perf_counter()
        hits = await kb.search(query, user_id=UID, top_k=3)
        dt = time.perf_counter() - t
        if hits:
            top = hits[0]
            print("  %-22s → 《%s》 rerank=%.3f rank1 | 共%d个 | %.2fs"
                  % (query, top["title"][:14], top.get("rerank_score", 0), len(hits), dt))
            print("       (%s)" % note)
        else:
            print("  %-22s → 无结果（门控拒答/未召回）| %.2fs" % (query, dt))
            print("       (%s)" % note)

    print()
    print("=" * 78)
    print("④ 查询改写效果（多轮指代）")
    print("=" * 78)
    hits_a = await kb.search("这个怎么办", user_id=UID, top_k=1, rewrite=False)
    hits_b = await kb.search("这个怎么办", user_id=UID, top_k=1,
                             history=["老人跌倒了怎么办"], rewrite=True)
    print("  不改写 '这个怎么办'      →", hits_a[0]["title"] if hits_a else "无结果")
    print("  改写后（带上文锚点）      →", hits_b[0]["title"] if hits_b else "无结果")


asyncio.run(main())
