# -*- coding: utf-8 -*-
"""Reranker（精排）。

移植自 E:\\enterprise-rag 的 app/reranker/（cosine + llm 两种；bge 本地
CrossEncoder 版不移植——本项目不引入额外模型权重）。

召回与精排的分工（enterprise-rag 的设计，值得保留）：
    Embedding 负责"召回"——双塔模型各自编码，快但 query/doc 从没见过彼此，
    所以召回阶段**宁多勿漏**（Top-20 宽进）；
    Reranker 负责"精排"——把 (query, doc) 放一起判断相关性，精度高但慢，
    只作用于召回后的少量候选。

本项目的 CosineReranker 有个便宜可占：入库时向量已经写在
KnowledgeChunk.embedding 里，精排时**直接查表复用，零额外网络往返**。
（enterprise-rag 的 Chroma 版本也是这个思路，见其 _fetch_or_embed。）
"""
from __future__ import annotations

import math
import re
from typing import Dict, List, Optional, Sequence, Tuple


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class CosineReranker:
    """余弦精排：用 query 向量与候选的**已存向量**重算语义相似度。

    为什么混合检索后必须做这一步：
        RRF 融合分是 1/(k+rank) 量纲（约 0.016~0.033），**不可解释、也无法设阈值**。
        精排把分数换回 0~1 的语义相似度，Top-K 才稳定，相关性门控也才有依据。
    """

    name = "cosine"

    def rerank(
        self,
        query_vec: Optional[List[float]],
        candidates: List[dict],
        top_k: int,
    ) -> List[dict]:
        """candidates 每项需含 chunk_id / content / embedding。"""
        if not candidates:
            return []
        for item in candidates:
            stored = item.get("embedding")
            if query_vec and stored:
                item["rerank_score"] = round(_cosine(query_vec, stored), 4)
            else:
                # 没有向量可比重算（BM25 独有召回 / 该 chunk 未建向量）：
                # 保留 RRF 融合分作为弱信号，标 0 表示"未经语义确认"
                item["rerank_score"] = round(float(item.get("score") or 0.0), 6)
        candidates.sort(key=lambda x: x["rerank_score"], reverse=True)
        for rank, item in enumerate(candidates[:top_k], start=1):
            item["rank"] = rank
            item["source"] = "rerank"
        return candidates[:top_k]


class LLMReranker:
    """LLM 精排（可选）：把候选编号后让 LLM 打 0~3 分。

    这是**最慢**的方案（每个候选都要过一次 LLM），仅在不敏感的场景
    （如家属端手动查询）按需启用；任何失败都降级到余弦精排，链路不中断。
    """

    name = "llm"

    def __init__(self, llm, embedding_query=None, cosine: Optional[CosineReranker] = None) -> None:
        self.llm = llm
        self.embedding_query = embedding_query  # async fn(text) -> vec
        self._cosine = cosine or CosineReranker()

    async def rerank(
        self,
        query: str,
        query_vec: Optional[List[float]],
        candidates: List[dict],
        top_k: int,
    ) -> List[dict]:
        if not candidates:
            return []
        if self.llm is None:
            return self._cosine.rerank(query_vec, candidates, top_k)
        numbered = "\n".join(
            f"{i + 1}. {(c.get('content') or '')[:200]}" for i, c in enumerate(candidates)
        )
        prompt = (
            "你是知识库相关性裁判。下面有一个问题和若干候选片段，"
            "请判断每个片段对**直接回答该问题**的相关程度并打分：\n"
            "0=完全无关  1=沾边但不直接回答  2=相关  3=直接命中\n"
            "只输出分数，用逗号分隔，顺序与编号一致，不要任何解释。\n\n"
            f"问题：{query}\n\n候选片段：\n{numbered}\n\n分数："
        )
        try:
            raw = (self.llm(prompt) or "").strip()
            scores = [float(s) for s in re.findall(r"[0-3](?:\.\d+)?", raw)]
            if len(scores) >= len(candidates):
                for item, s in zip(candidates, scores):
                    item["rerank_score"] = round(s, 3)
                candidates.sort(key=lambda x: x["rerank_score"], reverse=True)
                for rank, item in enumerate(candidates[:top_k], start=1):
                    item["rank"] = rank
                    item["source"] = "rerank_llm"
                return candidates[:top_k]
        except Exception:  # noqa: BLE001  打分失败降级，绝不影响检索
            pass
        return self._cosine.rerank(query_vec, candidates, top_k)


def build_reranker(backend: str = "cosine", llm=None, embedding_query=None):
    """按配置构造精排器：cosine（默认，零成本）/ llm / none。"""
    backend = (backend or "cosine").lower()
    if backend == "none":
        return None
    if backend == "llm":
        return LLMReranker(llm, embedding_query=embedding_query)
    return CosineReranker()
