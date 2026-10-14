"""推荐反馈数据访问层。"""
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RecommendationFeedback


class FeedbackRepo:
    """推荐反馈 CRUD。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self,
        user_id: str,
        recommendation_type: str,
        recommendation_title: str,
        feedback_type: str,
        conversation_id: Optional[int] = None,
    ) -> int:
        """添加一条反馈记录。"""
        fb = RecommendationFeedback(
            user_id=user_id,
            conversation_id=conversation_id,
            recommendation_type=recommendation_type,
            recommendation_title=recommendation_title,
            feedback_type=feedback_type,
        )
        self.session.add(fb)
        await self.session.flush()
        return fb.id

    async def get_acceptance_rate(self, user_id: str, rec_type: str) -> float:
        """计算某类推荐的历史接受率 = like / (like + dislike + skip)。"""
        stmt = select(RecommendationFeedback).where(
            RecommendationFeedback.user_id == user_id,
            RecommendationFeedback.recommendation_type == rec_type,
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        if not rows:
            return 0.5  # 默认中性
        like_count = sum(1 for r in rows if r.feedback_type == "like")
        total = len(rows)
        return like_count / total if total > 0 else 0.5

    async def get_liked_titles(self, user_id: str, rec_type: str) -> List[str]:
        """获取用户喜欢的推荐标题列表。"""
        stmt = select(RecommendationFeedback.recommendation_title).where(
            RecommendationFeedback.user_id == user_id,
            RecommendationFeedback.recommendation_type == rec_type,
            RecommendationFeedback.feedback_type == "like",
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_disliked_titles(self, user_id: str, rec_type: str) -> List[str]:
        """获取用户不喜欢的推荐标题列表。"""
        stmt = select(RecommendationFeedback.recommendation_title).where(
            RecommendationFeedback.user_id == user_id,
            RecommendationFeedback.recommendation_type == rec_type,
            RecommendationFeedback.feedback_type == "dislike",
        )
        return list((await self.session.execute(stmt)).scalars().all())
