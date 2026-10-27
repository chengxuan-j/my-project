"""时光信笺：给未来的自己 / 家人留一句话。

规则（写死在接口层，不靠前端自觉）：

- 未到 `deliver_at` 的信：只有老人本人能看，家属端一条都不返回；
- 到了 `deliver_at`：状态变 delivered；`visibility=family` 的才允许家属读；
- 已送达的信不允许再改、也不允许删——那已经不是草稿，是留给未来的东西了；
- 家属端只读，不能替老人写、也不能替老人拆信。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_elderly, require_family
from app.db.base import get_db
from app.db.models import Account, TimeLetter
from app.repositories.profile_repo import FamilyRepo
from app.schemas.care import LetterCreate, LetterUpdate
from app.services.health_care import as_local_naive, local_now

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/letters", tags=["letters"])
family_router = APIRouter(prefix="/family", tags=["family-letters"])

MAX_YEARS_AHEAD = 20


def _iso_local(dt: Optional[datetime]) -> str:
    """created_at 这类 server_default 列在 SQLite 里是 UTC 且无时区标记，
    直接 isoformat 前端当本地时间解析会差 8 小时。这里补上 UTC 再转本地。"""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().isoformat()


def _state(letter: TimeLetter, now: datetime) -> str:
    """把时间与持久状态合成对外状态：scheduled / delivered / read。"""
    if letter.status == "read":
        return "read"
    if letter.deliver_at <= now:
        return "delivered"
    return "scheduled"


def _to_dict(letter: TimeLetter, now: datetime) -> Dict[str, Any]:
    state = _state(letter, now)
    remaining = letter.deliver_at - now
    return {
        "id": letter.id,
        "title": letter.title or "",
        "content": letter.content,
        "recipient_type": letter.recipient_type,
        "recipient_name": letter.recipient_name or "",
        "deliver_at": letter.deliver_at.isoformat(),
        "visibility": letter.visibility,
        "status": state,
        "days_until": max(0, remaining.days) if state == "scheduled" else 0,
        "seconds_until": max(0, int(remaining.total_seconds())) if state == "scheduled" else 0,
        "opened_at": _iso_local(letter.opened_at) or None,
        "created_at": _iso_local(letter.created_at),
        "can_edit": state == "scheduled",
        "can_delete": state == "scheduled",
    }


def _resolve_deliver_at(raw: str, now: datetime) -> datetime:
    dt = as_local_naive(raw)
    if dt is None:
        raise HTTPException(status_code=422, detail="送达时间格式不正确")
    if dt > now + timedelta(days=365 * MAX_YEARS_AHEAD):
        raise HTTPException(status_code=422, detail=f"送达时间最多只能选 {MAX_YEARS_AHEAD} 年内")
    return dt


async def _get_letter(session: AsyncSession, user_id: str, letter_id: int) -> TimeLetter:
    letter = (await session.execute(
        select(TimeLetter).where(
            TimeLetter.id == letter_id,
            TimeLetter.elderly_user_id == user_id,
        )
    )).scalar_one_or_none()
    if letter is None:
        raise HTTPException(status_code=404, detail="这封信不存在")
    return letter


# ---------------------------------------------------------------------------
# 老人端
# ---------------------------------------------------------------------------

@router.get("")
async def list_letters(
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    now = local_now()
    rows = (await session.execute(
        select(TimeLetter)
        .where(TimeLetter.elderly_user_id == account.user_id)
        .order_by(TimeLetter.deliver_at.asc())
    )).scalars().all()

    items = [_to_dict(l, now) for l in rows]
    return {
        "letters": items,
        "scheduled": [i for i in items if i["status"] == "scheduled"],
        "delivered": [i for i in items if i["status"] == "delivered"],
        "read": [i for i in items if i["status"] == "read"],
        "unread_count": sum(1 for i in items if i["status"] == "delivered"),
    }


@router.get("/due")
async def due_letters(
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    """已送达但还没拆开的信——首页给个"有封信可以拆了"的提示。"""
    now = local_now()
    rows = (await session.execute(
        select(TimeLetter).where(
            TimeLetter.elderly_user_id == account.user_id,
            TimeLetter.status != "read",
            TimeLetter.deliver_at <= now,
        ).order_by(TimeLetter.deliver_at.asc())
    )).scalars().all()
    return {"count": len(rows), "letters": [_to_dict(l, now) for l in rows]}


@router.post("")
async def create_letter(
    req: LetterCreate,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    now = local_now()
    deliver_at = _resolve_deliver_at(req.deliver_at, now)
    if req.recipient_type == "family" and not req.recipient_name.strip():
        raise HTTPException(status_code=422, detail="写给家人的信，请填一下给谁")

    letter = TimeLetter(
        elderly_user_id=account.user_id,
        title=req.title.strip() or "给未来的一句话",
        content=req.content.strip(),
        recipient_type=req.recipient_type,
        recipient_name=req.recipient_name.strip(),
        deliver_at=deliver_at,
        visibility=req.visibility,
        status="scheduled",
    )
    session.add(letter)
    await session.commit()
    await session.refresh(letter)
    return _to_dict(letter, now)


@router.put("/{letter_id}")
async def update_letter(
    letter_id: int,
    req: LetterUpdate,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    now = local_now()
    letter = await _get_letter(session, account.user_id, letter_id)
    if _state(letter, now) != "scheduled":
        raise HTTPException(status_code=409, detail="这封信已经送达，不能再改了")

    if req.title is not None:
        letter.title = req.title.strip()
    if req.content is not None:
        letter.content = req.content.strip()
    if req.recipient_type is not None:
        letter.recipient_type = req.recipient_type
    if req.recipient_name is not None:
        letter.recipient_name = req.recipient_name.strip()
    if req.deliver_at is not None:
        letter.deliver_at = _resolve_deliver_at(req.deliver_at, now)
    if req.visibility is not None:
        letter.visibility = req.visibility
    if letter.recipient_type == "family" and not letter.recipient_name:
        raise HTTPException(status_code=422, detail="写给家人的信，请填一下给谁")

    await session.commit()
    await session.refresh(letter)
    return _to_dict(letter, now)


@router.post("/{letter_id}/open")
async def open_letter(
    letter_id: int,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    now = local_now()
    letter = await _get_letter(session, account.user_id, letter_id)
    if _state(letter, now) == "scheduled":
        raise HTTPException(status_code=409, detail="还没到拆信的日子")
    letter.status = "read"
    letter.opened_at = now
    await session.commit()
    await session.refresh(letter)
    return _to_dict(letter, now)


@router.delete("/{letter_id}")
async def delete_letter(
    letter_id: int,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    now = local_now()
    letter = await _get_letter(session, account.user_id, letter_id)
    if _state(letter, now) != "scheduled":
        raise HTTPException(status_code=409, detail="已经送达的信不能删")
    await session.delete(letter)
    await session.commit()
    return {"deleted": True, "id": letter_id}


# ---------------------------------------------------------------------------
# 家属端（只读：已送达 + 明确设了 family 可见）
# ---------------------------------------------------------------------------

@family_router.get("/elderly/{elderly_id}/letters")
async def family_letters(
    elderly_id: str,
    account: Account = Depends(require_family),
    session: AsyncSession = Depends(get_db),
):
    if not await FamilyRepo(session).exists(account.user_id, elderly_id):
        raise HTTPException(status_code=403, detail="未绑定该老人")
    now = local_now()
    rows = (await session.execute(
        select(TimeLetter).where(
            TimeLetter.elderly_user_id == elderly_id,
            TimeLetter.visibility == "family",
            TimeLetter.deliver_at <= now,
        ).order_by(TimeLetter.deliver_at.desc())
    )).scalars().all()

    return {
        "letters": [
            {
                "id": l.id,
                "title": l.title or "",
                "content": l.content,
                "recipient_type": l.recipient_type,
                "recipient_name": l.recipient_name or "",
                "deliver_at": l.deliver_at.isoformat(),
                "created_at": _iso_local(l.created_at),
            }
            for l in rows
        ],
        # 只报"有几封写给我的还没到时间"，不透露标题和内容；
        # 私密信连这个计数都不进——家属端不应该知道它的存在。
        "scheduled_count": len((await session.execute(
            select(TimeLetter.id).where(
                TimeLetter.elderly_user_id == elderly_id,
                TimeLetter.visibility == "family",
                TimeLetter.deliver_at > now,
            )
        )).scalars().all()),
        "generated_at": now.isoformat(),
    }
