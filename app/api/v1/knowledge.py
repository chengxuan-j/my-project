"""RAG 知识库管理与检索 API。"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.container import get_knowledge_base
from app.core.dependencies import require_family
from app.db.models import Account
from app.repositories.profile_repo import FamilyRepo
from app.rag.knowledge_base import KnowledgeBase
from app.db.base import get_db
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class KnowledgeDocumentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1, max_length=200_000)
    source: str = Field(default="", max_length=500)
    scope: str = Field(default="global", pattern="^(global|elderly)$")
    elderly_user_id: Optional[str] = Field(default=None, max_length=64)


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    elderly_user_id: Optional[str] = Field(default=None, max_length=64)


async def _check_elderly_scope(
    account: Account, elderly_user_id: Optional[str], session: AsyncSession
) -> None:
    if not elderly_user_id:
        raise HTTPException(status_code=400, detail="elderly 作用域必须指定老人")
    if not await FamilyRepo(session).exists(account.user_id, elderly_user_id):
        raise HTTPException(status_code=403, detail="只能管理已绑定老人的专属知识")


@router.post("/documents")
async def create_document(
    req: KnowledgeDocumentCreate,
    account: Account = Depends(require_family),
    session: AsyncSession = Depends(get_db),
    knowledge: KnowledgeBase = Depends(get_knowledge_base),
) -> Dict[str, Any]:
    """导入一篇文本知识。内容会自动分块并尝试生成 embedding。"""
    if req.scope == "elderly":
        await _check_elderly_scope(account, req.elderly_user_id, session)
    try:
        return await knowledge.add_document(
            req.title, req.content, source=req.source, scope=req.scope,
            elderly_user_id=req.elderly_user_id, created_by=account.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/documents")
async def list_documents(
    account: Account = Depends(require_family),
    knowledge: KnowledgeBase = Depends(get_knowledge_base),
) -> Dict[str, Any]:
    """列出家属可管理的文档。老人端不暴露知识库管理界面。"""
    return {"documents": await knowledge.list_visible_documents(account.user_id, account.role)}


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: int,
    account: Account = Depends(require_family),
    knowledge: KnowledgeBase = Depends(get_knowledge_base),
) -> Dict[str, Any]:
    if not await knowledge.delete_document(document_id, created_by=account.user_id):
        raise HTTPException(status_code=404, detail="知识文档不存在或无权删除")
    return {"deleted": True, "id": document_id}


@router.post("/search")
async def search_knowledge(
    req: KnowledgeSearchRequest,
    account: Account = Depends(require_family),
    session: AsyncSession = Depends(get_db),
    knowledge: KnowledgeBase = Depends(get_knowledge_base),
) -> Dict[str, Any]:
    """手动测试检索结果；聊天流程会自动执行同样的检索。"""
    user_id = account.user_id
    if req.elderly_user_id:
        await _check_elderly_scope(account, req.elderly_user_id, session)
        user_id = req.elderly_user_id
    results = await knowledge.search(
        req.query, user_id=user_id, created_by=account.user_id, top_k=req.top_k
    )
    return {"query": req.query, "results": results}
