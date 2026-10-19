"""轻量 RAG 知识库：文档分块、Embedding 存储与**混合检索**。

检索链路（2026-10-19 起按 E:\\enterprise-rag 的结构重写）：

    查询改写（规则门控）
      → 向量召回 ∥ BM25 召回（各 Top-20 宽进）
      → RRF 融合（只用名次，免疫量纲差异）
      → 余弦精排（复用入库向量，换回可解释的 0~1 相似度）
      → 相关性门控（top1 过低则判定"库里没有"，返回空）

存储仍用 SQL 表（KnowledgeChunk.embedding 存 JSON 向量），
适合当前规模与 SQLite/PostgreSQL 双环境；数据量明显增大时可只替换
``_load_visible_chunks`` 为 pgvector，上层 API 不变。
"""
import hashlib
import inspect
import logging
import math
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy import delete, or_, and_, select

from app.db.base import get_session_factory
from app.db.models import FamilyElderlyBinding, KnowledgeChunk, KnowledgeDocument
from app.llm.qwen_client import LLMError, QwenClient
from app.rag.bm25 import BM25Index
from app.rag.hybrid import RRF_K, rrf_fuse
from app.rag.rerank import CosineReranker
from app.rag.rewrite import QueryRewriter

logger = logging.getLogger(__name__)

CHUNK_SIZE = 500
CHUNK_OVERLAP = 80
MAX_DOCUMENT_CHARS = 200_000
DEFAULT_TOP_K = 5

# ---- 混合检索参数（对齐 enterprise-rag 的 config 默认值）----
RETRIEVE_TOP_K = 20      # 召回阶段宽进：宁多勿漏
RRF_K = RRF_K            # RRF 平滑常数（工业界常用 60）
# 相关性门控阈值：精排（余弦）后 top1 低于此值 → 判定知识库没有相关内容。
# 取 0.50 的依据（2026-10-19 实测 6 个正确查询 + 2 个无关查询）：
#   正确命中最低 0.568，无关查询最高 0.435 —— 两者之间有间隙，取中值并留余量。
# 低于此仍把内容塞进 prompt，只会诱导模型"拿着不相干的资料编故事"。
RELEVANCE_THRESHOLD = 0.50


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _bigrams(text: str) -> set[str]:
    compact = "".join(text.split())
    return {compact[i:i + 2] for i in range(len(compact) - 1)} if len(compact) > 1 else set()


def lexical_score(query: str, content: str) -> float:
    """Embedding 不可用时的中文字符重合兜底。"""
    query_terms = set(re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9]+", query.lower()))
    content_terms = set(re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9]+", content.lower()))
    unigram = len(query_terms & content_terms) / max(len(query_terms), 1)
    qb, cb = _bigrams(query), _bigrams(content)
    bigram = len(qb & cb) / max(len(qb), 1)
    return max(unigram, bigram)


def split_text(text: str, chunk_size: int = CHUNK_SIZE,
               overlap: int = CHUNK_OVERLAP) -> List[str]:
    """按段落/句子优先切分，保留少量重叠以避免上下文断裂。"""
    text = re.sub(r"\r\n?", "\n", text).strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    units = [u.strip() for u in re.split(r"(?<=[。！？!?；;])|\n+", text) if u.strip()]
    chunks: List[str] = []
    current = ""
    for unit in units:
        if len(unit) > chunk_size:
            if current:
                chunks.append(current)
                current = ""
            start = 0
            while start < len(unit):
                part = unit[start:start + chunk_size]
                chunks.append(part)
                start += max(1, chunk_size - overlap)
            continue
        candidate = f"{current}\n{unit}" if current else unit
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            chunks.append(current)
            tail = current[-overlap:] if overlap else ""
            current = f"{tail}\n{unit}".strip()
    if current:
        chunks.append(current)
    return chunks


class KnowledgeBase:
    """知识库服务。``embed_fn`` 可注入同步/异步函数，便于离线测试。"""

    def __init__(self, embed_fn: Optional[Callable[[List[str]], Any]] = None,
                 reranker: Optional[CosineReranker] = None,
                 rewriter: Optional[QueryRewriter] = None) -> None:
        self._embed_fn = embed_fn
        # 精排器与改写器可注入（测试/不同场景复用）；默认 cosine 精排 + 规则改写
        self._reranker = reranker or CosineReranker()
        self._rewriter = rewriter if rewriter is not None else QueryRewriter()
        # BM25 索引缓存：(失效键, 索引)；失效键 = (chunk 数, 最大 chunk_id)
        self._bm25_cache: Optional[Tuple[Tuple[int, int], BM25Index]] = None

    async def _embed(self, texts: List[str]) -> Optional[List[List[float]]]:
        if not texts:
            return []
        if self._embed_fn is None:
            self._embed_fn = QwenClient().embed
        try:
            result = self._embed_fn(texts)
            if inspect.isawaitable(result):
                result = await result
            if not result or len(result) != len(texts):
                return None
            return result
        except (LLMError, Exception) as exc:  # noqa: BLE001
            logger.info("知识库 embedding 不可用，检索降级为词面匹配: %s", exc)
            return None

    async def add_document(
        self,
        title: str,
        content: str,
        *,
        source: str = "",
        scope: str = "global",
        elderly_user_id: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        title = title.strip()[:200]
        content = content.strip()
        source = source.strip()[:500]
        if not title:
            raise ValueError("文档标题不能为空")
        if not content:
            raise ValueError("文档内容不能为空")
        if len(content) > MAX_DOCUMENT_CHARS:
            raise ValueError(f"文档内容不能超过 {MAX_DOCUMENT_CHARS} 个字符")
        if scope not in {"global", "elderly"}:
            raise ValueError("scope 只能是 global 或 elderly")
        if scope == "elderly" and not elderly_user_id:
            raise ValueError("elderly 作用域必须指定 elderly_user_id")
        if scope == "global":
            elderly_user_id = None

        chunks = split_text(content)
        embeddings = await self._embed_in_batches(chunks)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        factory = get_session_factory()
        async with factory() as session:
            existing = (await session.execute(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.content_hash == digest,
                    KnowledgeDocument.scope == scope,
                    KnowledgeDocument.elderly_user_id == elderly_user_id,
                    KnowledgeDocument.created_by == created_by,
                )
            )).scalar_one_or_none()
            if existing is not None:
                return await self.get_document(existing.id)  # type: ignore[return-value]

            doc = KnowledgeDocument(
                title=title, source=source, scope=scope,
                elderly_user_id=elderly_user_id,
                content_hash=digest, created_by=created_by,
            )
            session.add(doc)
            await session.flush()
            for index, chunk in enumerate(chunks):
                session.add(KnowledgeChunk(
                    document_id=doc.id, chunk_index=index, content=chunk,
                    embedding=embeddings[index] if embeddings else None,
                ))
            await session.commit()
            return {
                "id": doc.id, "title": doc.title, "source": doc.source,
                "scope": doc.scope, "elderly_user_id": doc.elderly_user_id,
                "chunk_count": len(chunks), "embedded": bool(embeddings),
                "created_at": doc.created_at.isoformat() if doc.created_at else "",
            }

    async def _embed_in_batches(self, chunks: List[str], batch_size: int = 16) -> Optional[List[List[float]]]:
        if not chunks:
            return []
        vectors: List[List[float]] = []
        for start in range(0, len(chunks), batch_size):
            batch = await self._embed(chunks[start:start + batch_size])
            if batch is None:
                return None
            vectors.extend(batch)
        return vectors

    async def reindex_missing(self, batch_size: int = 16) -> int:
        """为尚无 embedding 的分块补建向量，返回成功更新数量。"""
        factory = get_session_factory()
        async with factory() as session:
            all_chunks = list((await session.execute(
                select(KnowledgeChunk)
                .order_by(KnowledgeChunk.id)
            )).scalars().all())
            # SQLAlchemy JSON 在 SQLite 可能把 Python None 存成 JSON `null`，
            # ORM 读取后同样是 None；在 Python 层筛选可同时兼容 SQLite/PostgreSQL。
            chunks = [chunk for chunk in all_chunks if chunk.embedding is None]
            updated = 0
            for start in range(0, len(chunks), batch_size):
                batch = chunks[start:start + batch_size]
                vectors = await self._embed([chunk.content for chunk in batch])
                if vectors is None:
                    break
                for chunk, vector in zip(batch, vectors):
                    chunk.embedding = vector
                    updated += 1
            if updated:
                await session.commit()
            return updated

    async def get_document(self, document_id: int) -> Optional[Dict[str, Any]]:
        factory = get_session_factory()
        async with factory() as session:
            doc = await session.get(KnowledgeDocument, document_id)
            if doc is None:
                return None
            count = (await session.execute(
                select(KnowledgeChunk.id).where(KnowledgeChunk.document_id == document_id)
            )).all()
            return self._document_dict(doc, len(count))

    async def list_documents(self, *, created_by: Optional[str] = None,
                             elderly_user_id: Optional[str] = None,
                             include_system: bool = False) -> List[Dict[str, Any]]:
        factory = get_session_factory()
        async with factory() as session:
            stmt = select(KnowledgeDocument).order_by(KnowledgeDocument.id.desc())
            if created_by is not None:
                owner_filter = KnowledgeDocument.created_by == created_by
                if include_system:
                    owner_filter = or_(owner_filter, KnowledgeDocument.created_by.is_(None))
                stmt = stmt.where(owner_filter)
            if elderly_user_id is not None:
                stmt = stmt.where(KnowledgeDocument.elderly_user_id == elderly_user_id)
            docs = list((await session.execute(stmt)).scalars().all())
            output = []
            for doc in docs:
                count = (await session.execute(
                    select(KnowledgeChunk.id).where(KnowledgeChunk.document_id == doc.id)
                )).all()
                output.append(self._document_dict(doc, len(count)))
            return output

    async def list_visible_documents(self, user_id: str, role: str) -> List[Dict[str, Any]]:
        """列出账号可见的文档摘要；老人只能看到公共/本人专属资料。"""
        factory = get_session_factory()
        async with factory() as session:
            if role == "family":
                stmt = select(KnowledgeDocument).where(
                    or_(KnowledgeDocument.created_by == user_id,
                        KnowledgeDocument.created_by.is_(None))
                )
            else:
                stmt = select(KnowledgeDocument).where(
                    or_(
                        and_(KnowledgeDocument.scope == "global",
                             KnowledgeDocument.created_by.is_(None)),
                        and_(KnowledgeDocument.scope == "elderly",
                             KnowledgeDocument.elderly_user_id == user_id),
                    )
                )
            docs = list((await session.execute(
                stmt.order_by(KnowledgeDocument.id.desc())
            )).scalars().all())
            output = []
            for doc in docs:
                count = (await session.execute(
                    select(KnowledgeChunk.id).where(KnowledgeChunk.document_id == doc.id)
                )).all()
                output.append(self._document_dict(doc, len(count)))
            return output

    async def delete_document(self, document_id: int, *, created_by: Optional[str] = None) -> bool:
        factory = get_session_factory()
        async with factory() as session:
            doc = await session.get(KnowledgeDocument, document_id)
            if doc is None or (created_by is not None and doc.created_by != created_by):
                return False
            await session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id))
            await session.delete(doc)
            await session.commit()
            return True

    async def search(self, query: str, *, user_id: Optional[str] = None,
                     created_by: Optional[str] = None,
                     top_k: int = DEFAULT_TOP_K,
                     history: Optional[List[str]] = None,
                     rewrite: bool = True) -> List[Dict[str, Any]]:
        """混合检索：改写 → 向量+BM25 双路召回 → RRF 融合 → 余弦精排 → 门控。

        链路移植自 E:\\enterprise-rag 的 app/pipeline/rag.py（在线侧 ask），
        存储仍用本项目的 SQL 表，对外返回结构与改造前一致（新增 rank /
        rerank_score / source 三个可选字段，不影响既有调用方）。

        与改造前的差别（改造前是"语义分与词面分二选一"）：
          ① 两路召回改为 **RRF 融合**，量纲问题不再存在，命中任一路的块都能进来；
          ② 新增**余弦精排**，把融合分换回可解释的 0~1 语义相似度
             （直接复用入库向量，零额外网络往返）；
          ③ 新增**相关性门控**：精排后 top1 仍低于阈值，说明知识库里没有真正
             相关的内容——此时返回空，让上层走"无知识库"路径，
             而不是把弱相关内容塞进 prompt 诱导模型编故事；
          ④ 新增**规则门控的查询改写**，多轮里的"这个怎么办"不再扑空。

        返回的 score 字段含义与改造前保持兼容（语义相似度 0~1），
        精排分见 rerank_score。
        """
        query = (query or "").strip()
        if not query:
            return []
        top_k = max(1, min(top_k, 20))
        timings: Dict[str, float] = {}
        t_all = time.perf_counter()

        # ---- 0) 查询改写（规则门控，默认不调 LLM）----
        effective_query = query
        if rewrite:
            t = time.perf_counter()
            effective_query, used_rewrite = self._rewriter.rewrite(query, history)
            timings["rewrite"] = time.perf_counter() - t
            if used_rewrite and effective_query != query:
                logger.info("知识库查询改写：%r → %r", query, effective_query)

        # ---- 1) 取候选池（可见性过滤 + 带上向量）----
        t = time.perf_counter()
        rows = await self._load_visible_chunks(user_id=user_id, created_by=created_by)
        timings["load"] = time.perf_counter() - t
        if not rows:
            return []

        # ---- 2) query 向量（一次调用，向量路与精排路共用）----
        t = time.perf_counter()
        query_vecs = await self._embed([effective_query])
        query_vec = query_vecs[0] if query_vecs else None
        timings["embed"] = time.perf_counter() - t

        # ---- 3) 双路召回（宁多勿漏：宽进 top_k_retrieve）----
        t = time.perf_counter()
        by_id = {r["chunk_id"]: r for r in rows}
        vector_ranked: List[Tuple[int, float]] = []
        if query_vec:
            scored_vec = [
                (cid, _cosine(query_vec, item.get("embedding") or []))
                for cid, item in by_id.items() if item.get("embedding")
            ]
            scored_vec.sort(key=lambda kv: kv[1], reverse=True)
            vector_ranked = [(cid, s) for cid, s in scored_vec[:RETRIEVE_TOP_K] if s > 0]

        bm25_index = self._get_bm25_index(rows)
        bm25_ranked = bm25_index.search(effective_query, top_k=RETRIEVE_TOP_K)
        timings["retrieve"] = time.perf_counter() - t

        if not vector_ranked and not bm25_ranked:
            logger.info("知识库双路均无召回（query=%r）", effective_query[:40])
            return []

        # ---- 4) RRF 融合 ----
        t = time.perf_counter()
        fused = rrf_fuse(vector_ranked, bm25_ranked, rrf_k=RRF_K)
        candidates: List[Dict[str, Any]] = []
        for cid, fused_score, source in fused[:RETRIEVE_TOP_K]:
            item = dict(by_id[cid])
            item["score"] = round(fused_score, 6)   # RRF 分（无量纲，仅用于召回排序）
            item["fused_score"] = item["score"]
            item["recall_source"] = source
            candidates.append(item)
        timings["fuse"] = time.perf_counter() - t

        # ---- 5) 精排（换回可解释的语义相似度）----
        t = time.perf_counter()
        ranked = self._reranker.rerank(query_vec, candidates, top_k)
        timings["rerank"] = time.perf_counter() - t

        # ---- 6) 相关性门控：top1 过低 → 宁可没有，不给弱上下文 ----
        if ranked:
            top_score = ranked[0].get("rerank_score", 0.0)
            if top_score < RELEVANCE_THRESHOLD:
                logger.info(
                    "知识库 top1 相关性 %.3f 低于阈值 %.3f，判定无相关内容（拒答）",
                    top_score, RELEVANCE_THRESHOLD,
                )
                return []

        timings["total"] = time.perf_counter() - t_all
        logger.info(
            "知识库检索：query=%r 候选=%d 精留=%d top1=%.3f | %s",
            effective_query[:40], len(candidates), len(ranked),
            ranked[0].get("rerank_score", 0.0) if ranked else 0.0,
            " ".join(f"{k}={v*1000:.0f}ms" for k, v in timings.items()),
        )
        return ranked

    # ------------------------------------------------------------------
    async def _load_visible_chunks(self, *, user_id: Optional[str],
                                   created_by: Optional[str]) -> List[Dict[str, Any]]:
        """按可见性取出候选 chunk（含向量）。可见性规则与改造前完全一致。"""
        factory = get_session_factory()
        try:
            async with factory() as session:
                # 系统公共资料（created_by 为空）对所有用户可见。
                # 家属创建的 global 资料只对该家属绑定的老人可见，防止跨家庭知识污染。
                visibility = and_(
                    KnowledgeDocument.scope == "global",
                    KnowledgeDocument.created_by.is_(None),
                )
                if created_by:
                    visibility = or_(
                        visibility,
                        KnowledgeDocument.created_by == created_by,
                    )
                if user_id:
                    family_ids = select(FamilyElderlyBinding.family_user_id).where(
                        FamilyElderlyBinding.elderly_user_id == user_id
                    )
                    visibility = or_(
                        visibility,
                        and_(
                            KnowledgeDocument.scope == "global",
                            KnowledgeDocument.created_by.in_(family_ids),
                        ),
                        and_(
                            KnowledgeDocument.scope == "elderly",
                            KnowledgeDocument.elderly_user_id == user_id,
                        ),
                    )
                stmt = (
                    select(KnowledgeChunk, KnowledgeDocument)
                    .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
                    .where(visibility)
                )
                rows = (await session.execute(stmt)).all()
        except Exception as exc:  # noqa: BLE001
            # 开发期间可能还没执行新版建表；知识库不可用不应阻断聊天。
            logger.warning("知识库检索失败，跳过 RAG: %s", exc)
            return []

        out: List[Dict[str, Any]] = []
        for chunk, doc in rows:
            out.append({
                "chunk_id": chunk.id, "document_id": doc.id,
                "title": doc.title, "source": doc.source,
                "scope": doc.scope, "content": chunk.content,
                "embedding": chunk.embedding,
                "score": 0.0,
            })
        return out

    def _get_bm25_index(self, rows: List[Dict[str, Any]]) -> BM25Index:
        """BM25 索引按 (chunk 数, 最大 id) 缓存；知识库有变动即重建。

        数据量小（本项目当前个位数~几十个 chunk），重建一次是毫秒级；
        用 id 做失效键，新增/删除文档后下一次检索自动拿到新索引。
        """
        key = (len(rows), max((r["chunk_id"] for r in rows), default=0))
        cached = self._bm25_cache
        if cached is None or cached[0] != key:
            index = BM25Index().build([(r["chunk_id"], r["content"]) for r in rows])
            self._bm25_cache = (key, index)
            return index
        return cached[1]

    @staticmethod
    def _document_dict(doc: KnowledgeDocument, chunk_count: int) -> Dict[str, Any]:
        return {
            "id": doc.id, "title": doc.title, "source": doc.source,
            "scope": doc.scope, "elderly_user_id": doc.elderly_user_id,
            "chunk_count": chunk_count,
            "created_by": doc.created_by,
            "created_at": doc.created_at.isoformat() if doc.created_at else "",
            "updated_at": doc.updated_at.isoformat() if doc.updated_at else "",
        }
