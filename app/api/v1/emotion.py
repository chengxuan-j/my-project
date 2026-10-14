"""情绪历史 + 短期记忆状态。"""
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException

from app.core.container import get_memory_manager
from app.core.dependencies import get_current_account, require_elderly, require_family
from app.db.base import get_db
from app.db.models import Account
from app.memory.memory_manager import MemoryManager
from app.repositories.profile_repo import ConversationRepo, FamilyRepo
from app.schemas import EmotionTrendDay
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/emotion", tags=["emotion"])


@router.get("/history")
async def emotion_history(
    limit: int = 20,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    limit = max(1, min(limit, 100))
    records = await ConversationRepo(session).list_emotions(account.user_id, limit)
    return {"user_id": account.user_id, "records": [
        {"emotion": r.emotion, "intensity": r.intensity,
         "created_at": r.created_at.isoformat() if r.created_at else ""}
        for r in records
    ]}


@router.get("/memory-state")
async def memory_state(
    account: Account = Depends(get_current_account),
    memory: MemoryManager = Depends(get_memory_manager),
):
    state = memory.short.current_state(account.user_id)
    recent = memory.short.recent_messages(account.user_id, turns=10)
    return {
        "state": state,
        "recent": [{"role": r, "content": c} for r, c in recent],
    }


@router.get("/trend", response_model=List[EmotionTrendDay])
async def emotion_trend(
    days: int = 7,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    """老人自己的情绪趋势（按天聚合）。"""
    days = max(1, min(days, 30))
    records = await ConversationRepo(session).list_emotions(account.user_id, limit=1000)
    return _aggregate_by_day(records, days)


@router.get("/{elderly_id}/trend", response_model=List[EmotionTrendDay])
async def elderly_emotion_trend(
    elderly_id: str,
    days: int = 7,
    account: Account = Depends(require_family),
    session: AsyncSession = Depends(get_db),
):
    """家属查看绑定老人的情绪趋势。"""
    repo = FamilyRepo(session)
    if elderly_id not in await repo.list_elderly(account.user_id):
        raise HTTPException(status_code=403, detail="未绑定该老人")
    days = max(1, min(days, 30))
    records = await ConversationRepo(session).list_emotions(elderly_id, limit=1000)
    return _aggregate_by_day(records, days)


def _aggregate_by_day(records, days: int) -> List[EmotionTrendDay]:
    """将情绪记录按天聚合。"""
    now = datetime.now()
    cutoff = now - timedelta(days=days)

    daily = defaultdict(list)
    for r in records:
        if r.created_at and r.created_at >= cutoff:
            day_key = r.created_at.strftime("%Y-%m-%d")
            daily[day_key].append(r)

    result = []
    for day in sorted(daily.keys(), reverse=True):
        day_records = daily[day]
        emotions = [r.emotion for r in day_records]
        intensities = [r.intensity for r in day_records]

        # 找出主导情绪（出现次数最多的）
        from collections import Counter
        emotion_counts = Counter(emotions)
        dominant = emotion_counts.most_common(1)[0][0] if emotion_counts else "neutral"

        avg_intensity = sum(intensities) / len(intensities) if intensities else 0.0

        result.append(EmotionTrendDay(
            date=day,
            dominant_emotion=dominant,
            avg_intensity=round(avg_intensity, 2),
            record_count=len(day_records),
        ))

    return result
