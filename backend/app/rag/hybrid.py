# -*- coding: utf-8 -*-
"""混合检索：向量（稠密）+ BM25（稀疏）双路召回，RRF 融合。

移植自 E:\\enterprise-rag 的 app/retrieval/hybrid.py。

为什么融合用 RRF 而不是分数加权：
    向量余弦是 [-1,1]，BM25 分是无上界浮点，量纲完全不可比。
    硬加权（0.5*cos + 0.5*bm25）会让 BM25 一个 12.3 的分把余弦 0.8 淹没，
    权重怎么调都别扭。RRF 只看**名次**：
        fused = Σ 1 / (k + rank_i)
    k 是平滑常数（常用 60）。两路都排前面的块融合分最高，天然免疫量纲问题，
    这也是工业界混合检索的默认方案。
"""
from __future__ import annotations

from typing import Dict, List, Tuple

RRF_K = 60


def rrf_fuse(
    vector_ranked: List[Tuple[int, float]],
    bm25_ranked: List[Tuple[int, float]],
    rrf_k: int = RRF_K,
) -> List[Tuple[int, float, str]]:
    """把两路「已按名次排好」的召回结果融合。

    参数：(chunk_id, score) 列表，调用前各自按分数降序。
    返回：[(chunk_id, fused_score, source), ...] 按融合分降序；
    source 标记该块被哪几路召回（vector / bm25 / both），便于排查召回来源。
    """
    contributions: Dict[int, float] = {}
    sources: Dict[int, set] = {}

    for label, ranked in (("vector", vector_ranked), ("bm25", bm25_ranked)):
        for rank, (chunk_id, _score) in enumerate(ranked, start=1):
            contributions[chunk_id] = contributions.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank)
            sources.setdefault(chunk_id, set()).add(label)

    fused = sorted(contributions.items(), key=lambda kv: kv[1], reverse=True)
    return [
        (cid, score, "both" if len(src) > 1 else next(iter(src)))
        for cid, score in fused
        for src in (sources[cid],)
    ]
