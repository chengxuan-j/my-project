"""APScheduler 调度器管理。

负责创建、注册任务、启动和停止调度器。
"""
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    """获取或创建调度器实例。"""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    return _scheduler


def register_jobs() -> None:
    """注册所有定时任务。"""
    from app.scheduler.jobs.proactive_checkin import (
        morning_greeting_job,
        evening_greeting_job,
        silence_detection_job,
        late_night_alert_job,
    )
    from app.scheduler.jobs.memory_consolidation import memory_consolidation_job
    from app.scheduler.jobs.emotion_alert import emotion_alert_check_job
    from app.scheduler.jobs.daily_digest import daily_digest_job

    scheduler = get_scheduler()
    settings = get_settings()

    # 主动问候
    scheduler.add_job(
        morning_greeting_job,
        CronTrigger(hour=8, minute=0),
        id="morning_greeting",
        name="早安问候",
        replace_existing=True,
    )
    scheduler.add_job(
        evening_greeting_job,
        CronTrigger(hour=19, minute=0),
        id="evening_greeting",
        name="晚安问候",
        replace_existing=True,
    )
    scheduler.add_job(
        silence_detection_job,
        IntervalTrigger(hours=4),
        id="silence_detection",
        name="沉默检测",
        replace_existing=True,
    )
    scheduler.add_job(
        late_night_alert_job,
        CronTrigger(hour=23, minute=30),
        id="late_night_alert",
        name="深夜提醒",
        replace_existing=True,
    )

    # 记忆整合
    scheduler.add_job(
        memory_consolidation_job,
        CronTrigger(hour=0, minute=0),
        id="memory_consolidation",
        name="每日记忆整合",
        replace_existing=True,
    )

    # 情绪告警
    scheduler.add_job(
        emotion_alert_check_job,
        CronTrigger(hour=21, minute=0),
        id="emotion_alert_check",
        name="情绪趋势告警检测",
        replace_existing=True,
    )

    # 每日陪伴日报（推送家属端；可用 .env 的 DIGEST_HOUR/DIGEST_MINUTE 调整时刻）
    if settings.digest_enabled:
        scheduler.add_job(
            daily_digest_job,
            CronTrigger(hour=settings.digest_hour, minute=settings.digest_minute),
            id="daily_digest",
            name="每日陪伴日报",
            replace_existing=True,
        )

    logger.info("已注册 %d 个定时任务", len(scheduler.get_jobs()))


async def start_scheduler() -> None:
    """启动调度器。

    生产环境默认启动；开发环境默认跳过（避免本地跑出一堆定时副作用），
    本地验证时在 .env 设 SCHEDULER_ENABLED=true 即可开启。
    """
    settings = get_settings()
    if settings.environment == "development" and not settings.scheduler_enabled:
        logger.info("开发环境且未开启 SCHEDULER_ENABLED，跳过调度器启动")
        return

    scheduler = get_scheduler()
    register_jobs()
    scheduler.start()
    logger.info("调度器已启动，共 %d 个任务", len(scheduler.get_jobs()))


async def stop_scheduler() -> None:
    """停止调度器。"""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("调度器已停止")
