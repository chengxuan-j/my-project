"""老人端偏好设置：目前只有方言模式。

为什么单独开一个接口，而不是走 PUT /profile：
- `/profile` 的更新是"整段覆盖"，前端少传一个 `conversation_preferences` 就会
  把别处的偏好（比如 health_note）冲掉；
- 方言开关是高频的小动作（聊天页、导航栏都可能点），需要一条窄而稳的写路径。
"""

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.companion.dialects import dialect_options, normalize_dialect
from app.core.dependencies import require_elderly
from app.db.base import get_db
from app.db.models import Account
from app.repositories.profile_repo import ProfileRepo
from app.schemas.care import DialectSettingRequest

router = APIRouter(prefix="/settings", tags=["settings"])


async def _read_state(session: AsyncSession, user_id: str) -> Dict[str, Any]:
    profile = await ProfileRepo(session).get(user_id)
    prefs = dict(profile.conversation_preferences or {}) if profile else {}
    dialect = (profile.dialect if profile else "") or ""
    enabled = bool(prefs.get("dialect_mode")) and bool(dialect)
    return {
        "enabled": enabled,
        # 关掉方言时仍把上次选的方言带回去，下次打开不用重选
        "dialect": dialect or "普通话",
        "active_dialect": dialect if enabled else "",
        "options": dialect_options(),
    }


@router.get("/dialect")
async def get_dialect(
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    return await _read_state(session, account.user_id)


@router.put("/dialect")
async def set_dialect(
    req: DialectSettingRequest,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    repo = ProfileRepo(session)
    profile = await repo.get(account.user_id)
    if profile is None:
        profile = await repo.upsert(account.user_id, {})

    selected = normalize_dialect(req.dialect)
    if req.enabled and not selected:
        raise HTTPException(status_code=422, detail="这个方言暂时还不支持，换一个试试")

    prefs = dict(profile.conversation_preferences or {})
    prefs["dialect_mode"] = bool(req.enabled)
    profile.conversation_preferences = prefs
    # 关掉时保留上次的选择：老人再打开还是原来的方言
    if selected:
        profile.dialect = selected
    await session.commit()
    await session.refresh(profile)
    return await _read_state(session, account.user_id)
