"""情绪趋势告警检测任务。

检查最近 3 天的情绪记录，如果连续 3 天出现负面情绪（intensity > 0.6），则创建告警。
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any

from app.db.legacy import get_conn
from app.repositories.alert_repo import AlertRepo
from app.db.base import get_session_factory

logger = logging.getLogger(__name__)

NEGATIVE_EMOTIONS = {"lonely", "sad", "worried", "anxious"}
THRESHOLD_INTENSITY = 0.6
CONSECUTIVE_DAYS = 3


def _get_active_elderly() -> List[str]:
    """获取最近 7 天活跃的老人 user_id 列表。"""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT DISTINCT user_id FROM conversations
               WHERE created_at >= datetime('now', '-7 days')"""
        ).fetchall()
    return [row["user_id"] for row in rows]


def _check_emotion_trend(user_id: str) -> bool:
    """检查最近 3 天是否连续负面情绪。"""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT DATE(created_at) as day, emotion, intensity
               FROM emotion_records
               WHERE user_id = ? AND created_at >= datetime('now', '-3 days')
               ORDER BY created_at""",
            (user_id,)
        ).fetchall()

    # 按天分组
    daily: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        day = row["day"]
        if day not in daily:
            daily[day] = []
        daily[day].append({"emotion": row["emotion"], "intensity": row["intensity"]})

    # 检查连续 3 天
    if len(daily) < 3:
        return False

    negative_days = 0
    for day in sorted(daily.keys()):
        has_negative = any(
            r["emotion"] in NEGATIVE_EMOTIONS and r["intensity"] > THRESHOLD_INTENSITY
            for r in daily[day]
        )
        if has_negative:
            negative_days += 1
        else:
            negative_days = 0
        if negative_days >= 3:
            return True
    return False


async def emotion_alert_check_job() -> None:
    """情绪趋势告警检测任务。"""
    logger.info("执行情绪趋势告警检测任务")
    elderly_list = _get_active_elderly()

    async with get_session_factory()() as session:
        alert_repo = AlertRepo(session)

        for user_id in elderly_list:
            if _check_emotion_trend(user_id):
                # 检查 24 小时内是否已有同类型告警
                has_recent = await alert_repo.check_recent_alert(
                    user_id, "negative_emotion_streak", hours=24
                )
                if not has_recent:
                    await alert_repo.create(
                        elderly_user_id=user_id,
                        alert_type="negative_emotion_streak",
                        severity="medium",
                        title="老人连续 3 天情绪低落",
                        detail=f"检测到 {user_id} 最近 3 天持续出现负面情绪，请关注。",
                    )
                    logger.info(f"创建情绪告警: user_id={user_id}")

        await session.commit()
