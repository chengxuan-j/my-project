"""每日陪伴日报推送任务（默认每天 20:30，Asia/Shanghai）。

流程：
1. 找出今天有过聊天的老人；
2. 汇总当天对话 → 统计 + AI 摘要（digest_service）；
3. 给每位绑定家属写一条 FamilyMessage（category=digest，sender_role=elderly），
   家属打开看板即可看到「今日陪伴日报」；
4. 经 SSE 事件总线实时通知在线家属；
5. 同一老人同一天只推一次（重复执行安全）。

时区说明：库中 created_at 以本地时间（naive）存储（实测 CURRENT_TIMESTAMP 为 UTC
但应用写入路径用的是本地时间），因此按本地日期边界取「今天」与数据口径一致。
"""
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import distinct, select

from app.core.events import bus
from app.db.base import get_session_factory
from app.db.models import Conversation, ElderlyProfile, FamilyMessage
from app.repositories.family_message_repo import FamilyMessageRepo
from app.repositories.profile_repo import FamilyRepo
from app.services.digest_service import build_digest_payload

logger = logging.getLogger(__name__)

DIGEST_CATEGORY = "digest"


def _today_range() -> tuple[datetime, datetime]:
    """今天的本地起止边界（naive，与库中 created_at 口径一致）。"""
    now = datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


async def _list_today_active_elderly(session, day_start: datetime, day_end: datetime) -> list[str]:
    stmt = (
        select(distinct(Conversation.user_id))
        .where(Conversation.created_at >= day_start, Conversation.created_at < day_end)
    )
    return list((await session.execute(stmt)).scalars().all())


async def _has_digest_today(session, elderly_user_id: str, day_start: datetime) -> bool:
    """今天是否已生成过该老人的日报（去重）。"""
    stmt = (
        select(FamilyMessage.id)
        .where(
            FamilyMessage.elderly_user_id == elderly_user_id,
            FamilyMessage.sender_role == "elderly",
            FamilyMessage.category == DIGEST_CATEGORY,
            FamilyMessage.created_at >= day_start,
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def daily_digest_job() -> None:
    """每日陪伴日报推送。"""
    logger.info("执行每日陪伴日报任务")
    day_start, day_end = _today_range()
    date_str = day_start.strftime("%Y-%m-%d")

    async with get_session_factory()() as session:
        elderly_ids = await _list_today_active_elderly(session, day_start, day_end)
        if not elderly_ids:
            logger.info("今天没有聊天记录，跳过日报生成")
            return

        pushed = 0
        for elderly_user_id in elderly_ids:
            if await _has_digest_today(session, elderly_user_id, day_start):
                logger.info("老人 %s 今日日报已生成，跳过", elderly_user_id)
                continue

            # 当天全部对话（时间正序）
            conv_stmt = (
                select(Conversation)
                .where(
                    Conversation.user_id == elderly_user_id,
                    Conversation.created_at >= day_start,
                    Conversation.created_at < day_end,
                )
                .order_by(Conversation.id)
            )
            convs = list((await session.execute(conv_stmt)).scalars().all())
            if not convs:
                continue

            # 老人姓名
            prof = (await session.execute(
                select(ElderlyProfile.name).where(ElderlyProfile.user_id == elderly_user_id)
            )).scalar_one_or_none()
            elderly_name = prof or "老人家"

            payload = await build_digest_payload(elderly_name, convs, date_str)
            content = json.dumps(payload, ensure_ascii=False)

            family_ids = await FamilyRepo(session).list_family(elderly_user_id)
            if not family_ids:
                logger.info("老人 %s 未绑定家属，日报不推送", elderly_user_id)
                continue

            msg_repo = FamilyMessageRepo(session)
            for family_user_id in family_ids:
                await msg_repo.create(
                    family_user_id, elderly_user_id, content,
                    DIGEST_CATEGORY, sender_role="elderly",
                )
                # 实时通知在线家属
                bus.publish(
                    family_user_id,
                    {
                        "type": "family_digest",
                        "elderly_user_id": elderly_user_id,
                        "date": date_str,
                    },
                )
                pushed += 1

        await session.commit()
        logger.info("每日陪伴日报完成：%d 位老人，推送 %d 条", len(elderly_ids), pushed)
