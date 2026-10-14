"""画像路由：读取/更新老人画像、管理长期记忆。

修复点：
- SQLAlchemy ORM 对象不能直接 .model_dump()，手工转 dict
- 避免 account.elderly_profile lazy loading（async 不支持），改为查询
- 兼容前端字段：前端用 health(str)，后端模型没有，映射到 conversation_preferences.health_note
"""
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_account, require_elderly
from app.db.base import get_db
from app.db.models import Account, ElderlyProfile
from app.repositories.profile_repo import MemoryRepo, ProfileRepo
from app.schemas import MemoryItem, ProfileUpdateRequest

router = APIRouter(prefix="/profile", tags=["profile"])


def _profile_to_dict(p: ElderlyProfile) -> Dict[str, Any]:
    """ORM → 前端 dict。把 health 从 conversation_preferences 里提出来，方便前端表单。"""
    prefs = dict(p.conversation_preferences or {})
    health = prefs.pop("health_note", "")  # 取出来放顶层
    return {
        "user_id": p.user_id,
        "name": p.name,
        "age": p.age,
        "gender": p.gender,
        "dialect": p.dialect,
        "interests": p.interests or [],
        "favorite_music": p.favorite_music or [],
        "favorite_stories": p.favorite_stories or [],
        "family": p.family or [],
        "life_experience": p.life_experience or [],
        "conversation_preferences": prefs,
        "taboos": p.taboos or [],
        "health": health,
    }


def _patch_to_columns(patch: Dict[str, Any]) -> Dict[str, Any]:
    """前端 patch → ORM 列。health 字段塞回 conversation_preferences.health_note。"""
    cols: Dict[str, Any] = {}
    if "health" in patch:
        health_val = patch.pop("health")
        # 取现有 prefs，再加 health_note
        cols["_health_note"] = health_val  # 标记，repo 层处理
    cols.update(patch)
    return cols


@router.get("", response_model=Dict[str, Any])
async def get_profile(
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    repo = ProfileRepo(session)
    profile = await repo.get(account.user_id)
    if profile is None:
        # 注册了但没画像（异常情况），现场建一个空的
        profile = await repo.upsert(account.user_id, {})
        await session.commit()
    return _profile_to_dict(profile)


@router.put("", response_model=Dict[str, Any])
async def update_profile(
    req: ProfileUpdateRequest,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    patch = req.model_dump(exclude_unset=True, exclude_none=True)

    # health 字段：合并进 conversation_preferences.health_note
    health = patch.pop("health", None)

    repo = ProfileRepo(session)
    existing = await repo.get(account.user_id)
    if existing is None:
        existing = await repo.upsert(account.user_id, {})

    if health is not None:
        prefs = dict(existing.conversation_preferences or {})
        prefs["health_note"] = health
        patch["conversation_preferences"] = prefs

    if patch:
        profile = await repo.update_partial(account.user_id, patch)
    else:
        profile = existing
    await session.commit()
    await session.refresh(profile)
    return _profile_to_dict(profile)


# ---------- 记忆（挂在老人 user_id 下） ----------

@router.get("/memories", response_model=list[MemoryItem])
async def list_memories(account: Account = Depends(require_elderly),
                        session: AsyncSession = Depends(get_db)):
    repo = MemoryRepo(session)
    rows = await repo.list_all(account.user_id)
    return [
        MemoryItem(
            id=r.id,
            memory_type=r.memory_type,
            content=r.content,
            importance=r.importance,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]


@router.delete("/memories/{memory_id}")
async def delete_memory(
    memory_id: int,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    ok = await MemoryRepo(session).delete(account.user_id, memory_id)
    if not ok:
        raise HTTPException(status_code=404, detail="记忆不存在")
    await session.commit()
    return {"deleted": True, "id": memory_id}
