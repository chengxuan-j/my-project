"""情绪历史 + 短期记忆状态 + 摄像头表情识别（DeepFace）。"""
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.container import get_memory_manager
from app.core.dependencies import get_current_account, require_elderly, require_family
from app.core.events import bus
from app.db.base import get_db
from app.db.models import Account
from app.memory.memory_manager import MemoryManager
from app.repositories.profile_repo import ConversationRepo, FamilyRepo
from app.schemas import EmotionTrendDay, FaceEmotionResponse
from app.services.dog_control import execute_actions, push_to_dog
from app.services.face_emotion import FaceEmotionError, face_emotion, label_cn

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/emotion", tags=["emotion"])

# 与视觉接口一致的图片限制
MAX_IMAGE_SIZE = 5 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/bmp", "image/webp",
}

# 表情 → 机器狗反应动作 + 话术（固定短语，避免每次都走 LLM 拖慢响应）。
# 触发条件：同一表情连续 2 次识别（5 秒一帧，即持续约 5 秒）。
# neutral / surprise 不映射——平静时狗不该乱动，惊讶太瞬时容易误判。
REACTION_ACTIONS: dict[str, str] = {
    "happy": "前跳",
    "sad": "摇摆",
    "angry": "摇摆",
    "disgust": "鞠躬",
    "fear": "握手",
}
REACTION_SPEECH: dict[str, str] = {
    "happy": "看到您这么开心，我也高兴，给您跳个舞！",
    "sad": "我看您好像有点难过，我来给您摇摇尾巴，打打气！",
    "angry": "别生气别生气，我来跳个舞，逗您开心一笑！",
    "disgust": "心情不好吗？我给您鞠个躬，陪陪您！",
    "fear": "别怕别怕，我在这儿陪着您呢！",
}


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


@router.post("/face", response_model=FaceEmotionResponse)
async def emotion_face(
    file: UploadFile = File(...),
    react: bool = Form(default=False),
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    """摄像头表情识别：图片 → DeepFace 识别 → 情绪记录入库 + SSE 实时推送。

    前端老人端"表情识别"模式每 5 秒抓一帧调用本接口：
    - 识别结果叠加在摄像头画面上，同时写入 emotion_records（进情绪趋势/家属看板）；
    - 事件 face_emotion 实时推给老人本人和所有绑定家属；
    - react=True 且同一表情持续约 5 秒（连续 2 次识别）时，
      让机器狗做相应动作 + 说句话（开心庆祝、负面安慰）。
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="图片为空")
    if len(data) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=400, detail="图片超过 5MB")
    content_type = (file.content_type or "").lower()
    if content_type and content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="不支持的图片格式")

    try:
        result = await face_emotion.analyze(data)
    except FaceEmotionError as e:
        raise HTTPException(status_code=503, detail=str(e))

    if result is None:
        return FaceEmotionResponse(face_found=False, created_at=datetime.now().isoformat())

    emotion = result["emotion"]
    score = result["score"]
    state = face_emotion.update_state(account.user_id, emotion, score)

    # 入库：intensity 统一 0~1（deepface 得分是 0~100）
    repo = ConversationRepo(session)
    await repo.record_emotion(
        account.user_id, None, emotion=emotion, intensity=round(score / 100, 3)
    )
    await session.commit()

    # SSE：推给老人本人 + 所有绑定家属（家属看板实时显示"当前情绪"）
    created_at = datetime.now().isoformat()
    event = {
        "type": "face_emotion",
        "user_id": account.user_id,
        "emotion": emotion,
        "emotion_label": label_cn(emotion),
        "score": score,
        "created_at": created_at,
    }
    bus.publish(account.user_id, event)
    for family_id in await FamilyRepo(session).list_family(account.user_id):
        bus.publish(family_id, event)

    # 机器狗反应：同一表情持续约 5 秒（连续 2 次识别）且过了冷却期才触发
    dog_reacted = dog_reached = False
    speech = ""
    if react and emotion in REACTION_ACTIONS and face_emotion.should_react(account.user_id):
        action = REACTION_ACTIONS[emotion]
        speech = REACTION_SPEECH[emotion]
        settings = get_settings()
        dog_reached = await execute_actions(
            settings.dog_base_url, [(action, None)], timeout=settings.dog_timeout
        )
        dog_spoke = await push_to_dog(speech)
        face_emotion.mark_reacted(account.user_id)
        dog_reacted = True
        logger.info(
            "表情反应触发 user=%s emotion=%s action=%s reached=%s spoke=%s",
            account.user_id, emotion, action, dog_reached, dog_spoke,
        )

    logger.info(
        "表情识别完成 user=%s emotion=%s score=%s", account.user_id, emotion, score
    )
    return FaceEmotionResponse(
        face_found=True,
        emotion=emotion,
        emotion_label=label_cn(emotion),
        score=score,
        scores=result["scores"],
        region=result["region"],
        dog_reacted=dog_reacted,
        dog_reached=dog_reached,
        speech=speech,
        created_at=created_at,
    )


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
