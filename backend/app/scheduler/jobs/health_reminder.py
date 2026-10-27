"""定时任务：健康提醒扫描 + 时光信笺投递。

为什么不只在 API 里算：
- 老人不打开页面的时候，提醒也得"送到"（SSE 弹一下、家属端看得到）；
- 流水表要留下"某天某顿提醒发过"的事实，家属端的依从率才有据可查。

任务本身幂等：(kind, ref_id, scheduled_for) 唯一索引 + 已确认即跳过，
所以 5 分钟跑一次、甚至进程重启后重复跑，都不会把同一顿药提醒两次。
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.core.events import bus
from app.db.base import get_session_factory
from app.db.models import Account, HealthReminderLog, TimeLetter
from app.repositories.profile_repo import FamilyRepo
from app.services import health_care as svc

logger = logging.getLogger(__name__)


async def health_reminder_job() -> None:
    """扫描所有老人的待提醒事项，落流水 + 推 SSE。"""
    factory = get_session_factory()
    async with factory() as session:
        elderly_ids = (
            await session.execute(
                select(Account.user_id).where(
                    Account.role == "elderly", Account.is_active.is_(True)
                )
            )
        ).scalars().all()

    for user_id in elderly_ids:
        try:
            async with factory() as session:
                due = await svc.due_reminders(session, user_id)
                fresh = 0
                for item in due:
                    if item.get("log_status"):
                        continue  # 已经发过（未确认），不重复发
                    message = item["title"]
                    if item.get("detail"):
                        message = f"{message}（{item['detail']}）"
                    session.add(HealthReminderLog(
                        elderly_user_id=user_id,
                        kind=item["kind"],
                        ref_id=item["ref_id"],
                        scheduled_for=svc.as_local_naive(item["scheduled_for"]),
                        status="sent",
                        message=message,
                    ))
                    fresh += 1
                if fresh:
                    await session.commit()
                    for item in due:
                        if item.get("log_status"):
                            continue
                        bus.publish(user_id, {
                            "type": "health_reminder",
                            "kind": item["kind"],
                            "ref_id": item["ref_id"],
                            "title": item["title"],
                            "detail": item.get("detail", ""),
                            "scheduled_for": item["scheduled_for"],
                        })
                    logger.info("健康提醒已推送 user=%s 条数=%d", user_id, fresh)
        except Exception:
            logger.exception("健康提醒扫描失败 user=%s", user_id)


async def letter_delivery_job() -> None:
    """到点的时光信笺改为已送达，并通知老人（家属可见的同时通知家属）。"""
    factory = get_session_factory()
    now = svc.local_now()
    try:
        async with factory() as session:
            letters = (
                await session.execute(
                    select(TimeLetter).where(
                        TimeLetter.status == "scheduled",
                        TimeLetter.deliver_at <= now,
                    )
                )
            ).scalars().all()

            for letter in letters:
                letter.status = "delivered"
                bus.publish(letter.elderly_user_id, {
                    "type": "time_letter",
                    "letter_id": letter.id,
                    "title": letter.title,
                    "deliver_at": letter.deliver_at.isoformat(),
                })
                if letter.visibility == "family":
                    for family_id in await FamilyRepo(session).list_family(
                        letter.elderly_user_id
                    ):
                        bus.publish(family_id, {
                            "type": "time_letter",
                            "letter_id": letter.id,
                            "elderly_user_id": letter.elderly_user_id,
                            "title": letter.title,
                        })
            if letters:
                await session.commit()
                logger.info("时光信笺投递 %d 封", len(letters))
    except Exception:
        logger.exception("时光信笺投递任务失败")
