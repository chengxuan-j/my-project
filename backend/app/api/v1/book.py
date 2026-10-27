"""老人端「人生之书」：回忆录按人生阶段成书（仅老人本人）。"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_elderly
from app.db.base import get_db
from app.db.models import Account
from app.services.life_book import build_book

router = APIRouter(prefix="/book", tags=["book"])


@router.get("/me")
async def my_book(
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    """我的人生之书：封面 + 按人生阶段分的章节（自己的全部回忆）。"""
    return await build_book(session, account.user_id)
