# -*- coding: utf-8 -*-
"""BM25 稀疏检索（中文友好，零第三方依赖）。

移植自 E:\\enterprise-rag 的 app/retrieval/bm25.py，逻辑与公式一致，
适配到本项目的 SQL 存储（直接吃 KnowledgeChunk 行，不走向量库对象）。

为什么向量检索之外还要 BM25：
    向量（稠密）擅长语义近义，但对**精确关键词 / 专有名词 / 数字**容易翻车——
    "报销上限 5000 元" 里的 5000，在向量空间里和 4999/5001 几乎一样近；
    BM25 是字面匹配，5000 就是 5000。两者互补，混合后召回率明显更高。

公式（Okapi BM25）只三步，注释里拆开：
    score(q,d) = Σ_idf(t) * tf(t,d)*(k1+1) / (tf(t,d) + k1*(1-b+b*|d|/avgdl))
    ① tf 饱和：k1 控制"词频涨到多少就不再涨"，避免长文档堆词取胜
    ② idf   ：罕见词权重高（log((N-df+0.5)/(df+0.5)+1)）
    ③ 长度归一：b 控制"长文档是否该被惩罚"

分词：有 jieba 用 jieba，没有就退化成「ASCII 词 + 单个汉字」——
中文单字在 IDF 下也能跑（常见字会被压下去）。
"""
from __future__ import annotations

import math
import re
from typing import Callable, Dict, List, Sequence, Tuple

# 连续 ASCII 词（英文/数字）或单个 CJK 汉字
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]")


def default_tokenize(text: str) -> List[str]:
    """分词：有 jieba 用 jieba，没有退化为 ASCII 词 + 单字。"""
    text = (text or "").lower()
    try:
        import jieba  # type: ignore

        return [t for t in jieba.lcut(text) if t.strip()]
    except Exception:
        return _TOKEN_RE.findall(text)


class BM25Index:
    """最小可解释的 Okapi BM25 实现，带倒排索引（只给命中的文档打分）。"""

    def __init__(
        self,
        tokenizer: Callable[[str], List[str]] = default_tokenize,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.tokenize = tokenizer
        self.k1 = k1
        self.b = b
        self.doc_ids: List[int] = []
        self.doc_texts: List[str] = []
        self._doc_term_freqs: List[Dict[str, int]] = []
        self._doc_lengths: List[int] = []
        self._avgdl: float = 0.0
        self._n_docs: int = 0
        self._df: Dict[str, int] = {}
        # 倒排：term -> 包含它的文档下标列表，检索时只算这些文档
        self._postings: Dict[str, List[int]] = {}

    # ------------------------------------------------------------------
    def build(self, docs: Sequence[Tuple[int, str]]) -> "BM25Index":
        """建索引。docs 形如 [(chunk_id, content), ...]。"""
        self.doc_ids, self.doc_texts = [], []
        self._doc_term_freqs, self._doc_lengths = [], []
        self._df, self._postings = {}, {}

        for chunk_id, text in docs:
            tokens = self.tokenize(text)
            tf: Dict[str, int] = {}
            for tok in tokens:
                tf[tok] = tf.get(tok, 0) + 1
            index = len(self.doc_ids)
            self.doc_ids.append(chunk_id)
            self.doc_texts.append(text)
            self._doc_term_freqs.append(tf)
            self._doc_lengths.append(len(tokens))
            for term in tf:
                self._df[term] = self._df.get(term, 0) + 1
                self._postings.setdefault(term, []).append(index)

        self._n_docs = len(self.doc_ids)
        total = sum(self._doc_lengths)
        self._avgdl = (total / self._n_docs) if self._n_docs else 0.0
        return self

    # ------------------------------------------------------------------
    def _idf(self, term: str) -> float:
        """BM25+ 风格的非负 IDF：罕见词高分，满库常见的词趋近 0。"""
        df = self._df.get(term, 0)
        if df == 0 or self._n_docs == 0:
            return 0.0
        return math.log(1 + (self._n_docs - df + 0.5) / (df + 0.5))

    def search(self, query: str, top_k: int = 20) -> List[Tuple[int, float]]:
        """返回 [(chunk_id, score), ...]，按分数降序，只含得分 > 0 的。"""
        if self._n_docs == 0:
            return []
        q_terms = [t for t in self.tokenize(query) if t.strip()]
        if not q_terms:
            return []

        scores: Dict[int, float] = {}
        k1, b = self.k1, self.b
        for term in set(q_terms):
            idf = self._idf(term)
            if idf <= 0:
                continue
            for idx in self._postings.get(term, ()):
                tf = self._doc_term_freqs[idx].get(term, 0)
                if tf == 0:
                    continue
                dl = self._doc_lengths[idx] or 1
                denom = tf + k1 * (1 - b + b * dl / (self._avgdl or 1))
                scores[idx] = scores.get(idx, 0.0) + idf * tf * (k1 + 1) / denom

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        return [(self.doc_ids[i], s) for i, s in ranked[:top_k] if s > 0]
