"""推荐反馈 API。"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_account
from app.db.base import get_db
from app.db.models import Account
from app.repositories.feedback_repo import FeedbackRepo
from app.schemas import RecommendationFeedbackRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("/recommendation")
async def submit_recommendation_feedback(
    req: RecommendationFeedbackRequest,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
):
    """提交推荐反馈。"""
    repo = FeedbackRepo(session)
    feedback_id = await repo.add(
        user_id=account.user_id,
        recommendation_type=req.recommendation_type,
        recommendation_title=req.recommendation_title,
        feedback_type=req.feedback_type,
        conversation_id=req.conversation_id,
    )
    await session.commit()
    return {"feedback_id": feedback_id, "status": "ok"}
