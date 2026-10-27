"""老人端「人生河」：AI 陪伴成长 + 回忆时光河 + AI 画像卡。

只有老人本人能看（require_elderly）——这里汇的是老人自己的全部回忆，
不做任何可见性过滤：给老人看自己的东西，不需要家属那套契约。
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_elderly
from app.db.base import get_db
from app.db.models import Account, ElderlyProfile
from app.services.memory_insights import build_journey, build_portrait

router = APIRouter(prefix="/journey", tags=["journey"])


async def _elderly_name(session: AsyncSession, user_id: str) -> str:
    prof = (await session.execute(
        select(ElderlyProfile).where(ElderlyProfile.user_id == user_id)
    )).scalar_one_or_none()
    return prof.name if prof else ""


@router.get("/me")
async def my_journey(
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    """我的人生河：AI 越来越懂我 + 我的一生回忆按年代汇成河。"""
    name = await _elderly_name(session, account.user_id)
    return await build_journey(session, account.user_id, elderly_name=name)


@router.get("/portrait")
async def my_portrait(
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    """AI 眼中的你：爱好 / 重要的人 / 常聊话题 / 作息习惯。"""
    name = await _elderly_name(session, account.user_id)
    return await build_portrait(session, account.user_id, elderly_name=name)
