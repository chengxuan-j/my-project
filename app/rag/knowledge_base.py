"""轻量 RAG 知识库：文档分块、Embedding 存储与相似度检索。

向量先以 JSON 存在 SQLAlchemy 表中，适合当前规模和 SQLite/PostgreSQL 双环境。
后续数据量明显增大时，可以只替换 ``search`` 的存储实现为 pgvector，API 与上层上下文不变。
"""
import hashlib
import inspect
import logging
import math
import re
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import delete, or_, and_, select

from app.db.base import get_session_factory
from app.db.models import FamilyElderlyBinding, KnowledgeChunk, KnowledgeDocument
from app.llm.qwen_client import LLMError, QwenClient

logger = logging.getLogger(__name__)

CHUNK_SIZE = 500
CHUNK_OVERLAP = 80
MAX_DOCUMENT_CHARS = 200_000
DEFAULT_TOP_K = 5
SEMANTIC_MIN_SCORE = 0.42
LEXICAL_MIN_SCORE = 0.08


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

    def __init__(self, embed_fn: Optional[Callable[[List[str]], Any]] = None) -> None:
        self._embed_fn = embed_fn

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
                     top_k: int = DEFAULT_TOP_K) -> List[Dict[str, Any]]:
        query = query.strip()
        if not query:
            return []
        top_k = max(1, min(top_k, 20))
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
        if not rows:
            return []

        query_vecs = await self._embed([query])
        query_vec = query_vecs[0] if query_vecs else None
        scored: List[Dict[str, Any]] = []
        for chunk, doc in rows:
            semantic = _cosine(query_vec, chunk.embedding) if query_vec and chunk.embedding else 0.0
            lexical = lexical_score(query, chunk.content)
            has_embedding = bool(query_vec and chunk.embedding)
            # 语义分数未过门槛时，允许词面分数补召回，避免 embedding 偶发漂移漏掉明确关键词。
            if has_embedding and semantic >= SEMANTIC_MIN_SCORE:
                score = semantic
            elif lexical >= LEXICAL_MIN_SCORE:
                score = lexical
            else:
                continue
            scored.append({
                "chunk_id": chunk.id, "document_id": doc.id,
                "title": doc.title, "source": doc.source,
                "scope": doc.scope, "content": chunk.content,
                "score": round(min(score, 1.0), 4),
            })
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

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
