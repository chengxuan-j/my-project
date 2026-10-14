"""长期记忆：SQLite memories 表 + 语义检索。

检索策略（可降级）：
- 优先：embedding 向量余弦相似度（text-embedding-v3，远程 API）
- 兜底：字符 bigram 重合度（无 Key / embedding 失败 / 老数据无向量时）

不引入向量数据库，向量以 JSON 存在 memories.embedding 列，量级（每用户几十条）完全够用。
写入仍由 Qwen 判断（见 memory_extractor）。
"""
import json
import logging
import math
from typing import Any, Callable, Dict, List, Optional

from app.db import get_conn
from app.llm.qwen_client import LLMError, QwenClient

logger = logging.getLogger(__name__)

# 检索参数
TOP_K = 4
SIM_MIN = 0.50           # 语义检索余弦门槛（在 importance 加成前判定；宁缺毋滥，避免错误记忆注入 Prompt）
IMPORTANCE_BONUS = 0.5   # 排序加权：score = sim × (1 + importance×此值)，仅影响排序不影响命中
DEDUP_SIMILARITY = 0.88  # 语义去重阈值
BIGRAM_FALLBACK_MIN = 0.12  # bigram 兜底时的阈值


def _bigrams(text: str) -> set:
    t = "".join(text.split())
    return {t[i:i + 2] for i in range(len(t) - 1)} if len(t) > 1 else ({t} if t else set())


def bigram_relevance(query: str, content: str) -> float:
    """字符 bigram 重合度（0~1），作为语义检索的兜底。"""
    qb, cb = _bigrams(query), _bigrams(content)
    if not qb:
        return 0.0
    return len(qb & cb) / len(qb)


# 保留旧名，避免破坏既有测试
relevance = bigram_relevance


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class LongMemoryStore:

    def __init__(self, embed_fn: Optional[Callable[[List[str]], List[List[float]]]] = None):
        # embed_fn 可注入（测试用）；默认懒加载 QwenClient
        self._embed_fn = embed_fn

    async def _embed(self, texts: List[str]) -> List[List[float]]:
        """向量化；任何失败返回 None，由调用方降级到 bigram。"""
        if self._embed_fn is None:
            self._embed_fn = QwenClient().embed
        try:
            # embed_fn 可能是协程（异步）或同步函数，统一兼容
            import inspect
            if inspect.iscoroutinefunction(self._embed_fn):
                return await self._embed_fn(texts)
            return self._embed_fn(texts)
        except (LLMError, Exception) as e:  # noqa: BLE001
            logger.info("embedding 不可用，降级 bigram 检索: %s", e)
            return None

    async def add(self, user_id: str, memory_type: str, content: str,
                  importance: float = 0.5) -> Optional[int]:
        """写入一条记忆；语义相似则去重跳过（返回 None）。"""
        content = content.strip()
        if not content:
            return None
        importance = max(0.0, min(1.0, float(importance)))

        # 计算向量（失败则置空，检索时走 bigram）
        embedding = None
        vecs = await self._embed([content])
        if vecs:
            embedding = json.dumps(vecs[0])

        with get_conn() as conn:
            # 语义去重：与已有向量比对
            if embedding is not None:
                rows = conn.execute(
                    "SELECT id, content, embedding FROM memories WHERE user_id = ?",
                    (user_id,),
                ).fetchall()
                new_vec = json.loads(embedding)
                for row in rows:
                    if row["embedding"]:
                        try:
                            sim = _cosine(new_vec, json.loads(row["embedding"]))
                        except (json.JSONDecodeError, TypeError):
                            continue
                        if sim >= DEDUP_SIMILARITY:
                            logger.info("长期记忆语义去重跳过: %s (≈已有 id=%s)", content, row["id"])
                            return None
                    elif bigram_relevance(content, row["content"]) >= 0.75:
                        logger.info("长期记忆去重跳过: %s (≈已有 id=%s)", content, row["id"])
                        return None

            cur = conn.execute(
                """INSERT INTO memories (user_id, memory_type, content, importance, embedding)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, memory_type or "general", content, importance, embedding),
            )
            logger.info("长期记忆写入 id=%s type=%s: %s", cur.lastrowid, memory_type, content)
            return cur.lastrowid

    async def search_multi(self, user_id: str, queries: List[str],
                           top_k: int = TOP_K,
                           min_score: Optional[float] = None) -> List[Dict[str, Any]]:
        """多 query 批量检索：一次 embedding 调用算完所有 query，取每条记忆的最大相似度。

        用于替代"先搜 message、不够再搜 topic"的两次调用，省掉一次 API 往返。
        """
        queries = [q for q in queries if q and q.strip()]
        if not queries:
            return []
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT id, memory_type, content, importance, embedding, created_at
                   FROM memories WHERE user_id = ?""",
                (user_id,),
            ).fetchall()
        if not rows:
            return []

        # 一次调用算所有 query 的向量
        query_vecs = await self._embed(queries)
        if query_vecs and len(query_vecs) != len(queries):
            query_vecs = None

        scored = []
        for r in rows:
            best = 0.0
            if query_vecs is not None and r["embedding"]:
                try:
                    ev = json.loads(r["embedding"])
                    best = max((_cosine(qv, ev) for qv in query_vecs), default=0.0)
                except (json.JSONDecodeError, TypeError):
                    best = 0.0
            if best <= 0:
                best = max((bigram_relevance(q, r["content"]) for q in queries),
                           default=0.0)
            if best <= 0:
                continue
            if min_score is not None:
                gate = min_score
            else:
                gate = SIM_MIN if query_vecs is not None else BIGRAM_FALLBACK_MIN
            if best < gate:
                continue
            score = best * (1 + r["importance"] * IMPORTANCE_BONUS)
            scored.append({**dict(r), "embedding": None, "score": round(min(score, 1.0), 3)})

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    async def search(self, user_id: str, query: str,
                     top_k: int = TOP_K,
                     min_score: Optional[float] = None) -> List[Dict[str, Any]]:
        """语义检索：优先向量余弦，无向量/无 Key 时 bigram 兜底。"""
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT id, memory_type, content, importance, embedding, created_at
                   FROM memories WHERE user_id = ?""",
                (user_id,),
            ).fetchall()

        query_vec = None
        vecs = await self._embed([query])
        if vecs:
            query_vec = vecs[0]

        scored = []
        for r in rows:
            sim = 0.0
            if query_vec is not None and r["embedding"]:
                try:
                    sim = _cosine(query_vec, json.loads(r["embedding"]))
                except (json.JSONDecodeError, TypeError):
                    sim = 0.0
            if sim <= 0:
                # 兜底：bigram
                sim = bigram_relevance(query, r["content"])
            if sim <= 0:
                continue
            # 命中判定：语义检索用余弦门槛，bigram 兜底用低阈值；显式传入 min_score 可覆盖
            if min_score is not None:
                gate = min_score
            else:
                gate = SIM_MIN if query_vec is not None else BIGRAM_FALLBACK_MIN
            if sim < gate:
                continue
            # 排序分：importance 只做加权，不影响是否命中
            score = sim * (1 + r["importance"] * IMPORTANCE_BONUS)
            scored.append({**dict(r), "embedding": None, "score": round(min(score, 1.0), 3)})

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def list_all(self, user_id: str) -> List[Dict[str, Any]]:
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT id, memory_type, content, importance, created_at
                   FROM memories WHERE user_id = ? ORDER BY importance DESC, id DESC""",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete(self, user_id: str, memory_id: int) -> bool:
        with get_conn() as conn:
            cur = conn.execute(
                "DELETE FROM memories WHERE id = ? AND user_id = ?",
                (memory_id, user_id),
            )
            return cur.rowcount > 0
