"""主动关怀任务。

包含 4 个定时任务：
1. 早安问候（每天 8:00）
2. 晚安问候（每天 19:00）
3. 沉默检测（每 4 小时）
4. 深夜独居告警（每天 23:30）
"""
import logging
from datetime import datetime, timedelta
from typing import List

from app.db.legacy import get_conn
from app.agent.companion_agent import run as run_agent
from app.memory.memory_manager import MemoryManager

logger = logging.getLogger(__name__)


def _get_active_elderly() -> List[str]:
    """获取最近 7 天活跃的老人 user_id 列表。"""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT DISTINCT user_id FROM conversations
               WHERE created_at >= datetime('now', '-7 days')"""
        ).fetchall()
    return [row["user_id"] for row in rows]


def _get_last_conversation_time(user_id: str) -> datetime | None:
    """获取用户最后一次对话时间。"""
    with get_conn() as conn:
        row = conn.execute(
            """SELECT MAX(created_at) as last_time FROM conversations
               WHERE user_id = ?""",
            (user_id,)
        ).fetchone()
    if row and row["last_time"]:
        return datetime.fromisoformat(row["last_time"])
    return None


def _is_elderly_living_alone(user_id: str) -> bool:
    """判断老人是否独居（无家属绑定）。"""
    with get_conn() as conn:
        row = conn.execute(
            """SELECT COUNT(*) as cnt FROM family_elderly_bindings
               WHERE elderly_user_id = ?""",
            (user_id,)
        ).fetchone()
    return row["cnt"] == 0


async def _send_proactive_message(user_id: str, message: str, scene: str) -> None:
    """发送主动关怀消息。"""
    try:
        result = await run_agent(user_id, message)
        reply = result["reply"]
        
        # 保存到对话历史
        memory = MemoryManager()
        memory.short.append(user_id, "user", message, {"scene": scene})
        memory.short.append(user_id, "assistant", reply, {"scene": scene})
        
        logger.info(f"主动关怀消息已发送: user={user_id}, scene={scene}")
    except Exception as e:
        logger.error(f"发送主动关怀消息失败: user={user_id}, error={e}")


async def morning_greeting_job() -> None:
    """早安问候任务。"""
    logger.info("执行早安问候任务")
    elderly_list = _get_active_elderly()
    
    for user_id in elderly_list:
        await _send_proactive_message(
            user_id,
            "早上好！新的一天开始了，今天感觉怎么样？",
            "morning_greeting"
        )


async def evening_greeting_job() -> None:
    """晚安问候任务。"""
    logger.info("执行晚安问候任务")
    elderly_list = _get_active_elderly()
    
    for user_id in elderly_list:
        await _send_proactive_message(
            user_id,
            "晚上好！今天过得怎么样？早点休息哦。",
            "evening_greeting"
        )


async def silence_detection_job() -> None:
    """沉默检测任务：检测超过 4 小时未对话的用户。"""
    logger.info("执行沉默检测任务")
    elderly_list = _get_active_elderly()
    threshold = timedelta(hours=4)
    now = datetime.now()
    
    for user_id in elderly_list:
        last_time = _get_last_conversation_time(user_id)
        if last_time and (now - last_time) > threshold:
            # 检查是否在合理时间段（8:00-22:00）
            hour = now.hour
            if 8 <= hour < 22:
                await _send_proactive_message(
                    user_id,
                    "好久没聊天了，最近怎么样？有什么想说的吗？",
                    "silence_checkin"
                )


async def late_night_alert_job() -> None:
    """深夜独居告警任务。"""
    logger.info("执行深夜独居告警任务")
    elderly_list = _get_active_elderly()
    
    for user_id in elderly_list:
        if _is_elderly_living_alone(user_id):
            last_time = _get_last_conversation_time(user_id)
            if last_time:
                now = datetime.now()
                # 如果最近 30 分钟内有对话，说明还在熬夜
                if (now - last_time) < timedelta(minutes=30):
                    await _send_proactive_message(
                        user_id,
                        "这么晚了还没休息呀？早点睡觉对身体好哦。",
                        "late_night_alert"
                    )
