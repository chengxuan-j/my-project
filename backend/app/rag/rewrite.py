# -*- coding: utf-8 -*-
"""Query Rewrite（查询改写，规则门控）。

移植自 E:\\enterprise-rag 的 app/retrieval/rewrite.py，并按本项目场景调整：
- 默认**不调 LLM**（老人陪伴链路对延迟敏感，一次改写调用就是 0.3~1s）
- 门控命中时用「规则式轻量改写」：把最近一轮老人消息拼到 query 前，
  给指代词一个可检索的锚点。零延迟、可解释。
- LLM 改写保留为可选增强（传入 llm 即启用，适合家属端等不敏感场景）

它解决什么问题：
    多轮对话里"这个怎么办？""那报销呢？"单独看没有语义，检索会扑空。
    结合上文补全成独立可检索的问题才能召回。

为什么必须门控：
    简单问题（"年假几天？"）不需要改写，直接检索更快更准。
    所以只在命中下面任一条件时才动手：
      1. 含指代词（这个/那个/它/那报销…）
      2. 问题本身过短（< 6 字，大概率不完整）
      3. 存在多轮历史（当前句可能依赖上文）
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

_PRONOUN_RE = re.compile(r"(这个|那个|它|他|她|前者|后者|上面|上述|这|那)")
# 规则式改写时，从上文截取的最大长度（够给指代提供锚点即可）
_CONTEXT_ANCHOR_CHARS = 24


class QueryRewriter:
    """规则门控的查询改写器。llm 可省略（省略则只做规则式轻量改写）。"""

    def __init__(self, llm=None, min_len: int = 6, enabled: bool = True) -> None:
        self.llm = llm
        self.min_len = min_len
        self.enabled = enabled

    # ------------------------------------------------------------------
    def needs_rewrite(self, query: str, history: Optional[List[str]] = None) -> bool:
        if not self.enabled:
            return False
        q = (query or "").strip()
        if not q:
            return False
        if _PRONOUN_RE.search(q):
            return True
        if len(q) < self.min_len:
            return True
        if history and any(h.strip() for h in history):
            return True
        return False

    # ------------------------------------------------------------------
    def rewrite(self, query: str, history: Optional[List[str]] = None) -> Tuple[str, bool]:
        """返回 (改写后的 query, 是否改写)。门控不命中或改写失败都原样返回。"""
        query = (query or "").strip()
        history = [h.strip() for h in (history or []) if h.strip()]
        if not self.needs_rewrite(query, history):
            return query, False

        # 有 LLM 且可用 → 交给 LLM 补全（可选增强）
        if self.llm is not None:
            context = "\n".join(f"用户：{h}" for h in history[-3:])
            prompt = (
                "你是知识库问答系统的查询改写器。\n"
                "下面的最新问题可能依赖上文或含有指代，请补全成"
                "**独立、完整、可检索**的问题。\n"
                "只输出改写后的问题本身，不要解释，不要加引号。\n\n"
                f"对话历史：\n{context}\n\n最新问题：{query}\n\n改写后问题："
            )
            try:
                rewritten = (self.llm(prompt) or "").strip().strip("\"'")
                if rewritten:
                    return rewritten[:_CONTEXT_ANCHOR_CHARS * 3], True
            except Exception:  # noqa: BLE001  改写失败不该阻断检索
                pass

        # 无 LLM：规则式轻量改写——用最近一轮老人消息做锚点
        if history:
            anchor = history[-1][:_CONTEXT_ANCHOR_CHARS]
            if anchor and anchor not in query:
                return f"{anchor} {query}", True
        return query, False

    def __call__(self, query: str, history: Optional[List[str]] = None) -> Tuple[str, bool]:
        return self.rewrite(query, history)
