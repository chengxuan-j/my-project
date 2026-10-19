"""每日陪伴日报推送任务（默认每天 20:30，Asia/Shanghai）。

流程：
1. 找出今天「有动静」的老人——聊过天，**或**今天留档了新的回忆（M6）；
2. 汇总当天对话 → 统计 + AI 摘要（digest_service），并算上回忆录增量；
3. 给每位绑定家属写一条 FamilyMessage（category=digest，sender_role=elderly），
   家属打开看板即可看到「今日陪伴日报」；
4. 经 SSE 事件总线实时通知在线家属；
5. 同一老人同一天只推一次（重复执行安全）。

回忆录口径（M6）：只数**家属看得见**的（archived + visibility ∈ family/public）。
创伤类 private 故事不进计数，也不该以"今天新增 1 段"的方式被家属感知到——
那等于用数字泄了内容有没有（契约2）。

时区说明：库中 created_at 以本地时间（naive）存储（实测 CURRENT_TIMESTAMP 为 UTC
但应用写入路径用的是本地时间），因此按本地日期边界取「今天」与数据口径一致。
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import distinct, select

from app.core.events import bus
from app.db.base import get_session_factory
from app.db.models import Conversation, ElderlyProfile, FamilyMessage, LifeStory
from app.repositories.family_message_repo import FamilyMessageRepo
from app.repositories.profile_repo import FamilyRepo
from app.repositories.story_repo import StoryRepo
from app.services.digest_service import build_digest_payload

logger = logging.getLogger(__name__)

DIGEST_CATEGORY = "digest"


def _today_range() -> tuple[datetime, datetime]:
    """今天的本地起止边界（naive，与库中 created_at 口径一致）。"""
    now = datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def _week_start(day_start: datetime) -> datetime:
    """本周一 00:00（本地口径）。日报里"这周"用周一起算，比"近 7 天"更符合直觉。"""
    return day_start - timedelta(days=day_start.weekday())


async def _list_today_active_elderly(session, day_start: datetime, day_end: datetime) -> list[str]:
    stmt = (
        select(distinct(Conversation.user_id))
        .where(Conversation.created_at >= day_start, Conversation.created_at < day_end)
    )
    return list((await session.execute(stmt)).scalars().all())


async def _list_today_archived_elderly(session, day_start: datetime) -> list[str]:
    """今天留档过回忆的老人（按 `updated_at` 判，`set_status` 落档时会刷新）。"""
    stmt = (
        select(distinct(LifeStory.elderly_user_id))
        .where(
            LifeStory.status == "archived",
            LifeStory.updated_at.is_not(None),
            LifeStory.updated_at >= day_start,
        )
    )
    return list((await session.execute(stmt)).scalars().all())


async def _memoir_counts(session, elderly_user_id: str, day_start: datetime) -> dict[str, int]:
    """回忆录增量（只含家属可见的条目，契约2）。"""
    repo = StoryRepo(session)
    return {
        "today": await repo.count_family_visible(elderly_user_id, since=day_start),
        "week": await repo.count_family_visible(elderly_user_id, since=_week_start(day_start)),
        "total": await repo.count_family_visible(elderly_user_id),
    }


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


async def generate_digest_for(
    session,
    elderly_user_id: str,
    day_start: datetime,
    date_str: str,
) -> Optional[dict]:
    """为单个老人生成今日日报（无则生成、有则返回已有的）。

    定时任务与家属端「立即获取」接口共用这一条路径，保证两边口径一致：
    同一天只生成一次（重复调用返回已有内容，不重复花 LLM）。

    返回 None 表示今天没有可报的内容（没聊天、也没有新的可见回忆）。
    已绑定家属时顺带写 FamilyMessage + SSE 通知；未绑定家属时只返回 payload
    （给「立即获取」接口用——没绑定家属的老人，家属端根本调不到这个接口，
    但定时任务遍历到时要能安静跳过）。
    """
    from app.services.digest_service import parse_digest_content

    if await _has_digest_today(session, elderly_user_id, day_start):
        stmt = (
            select(FamilyMessage)
            .where(
                FamilyMessage.elderly_user_id == elderly_user_id,
                FamilyMessage.sender_role == "elderly",
                FamilyMessage.category == DIGEST_CATEGORY,
                FamilyMessage.created_at >= day_start,
            )
            .order_by(FamilyMessage.id.desc())
            .limit(1)
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            payload = parse_digest_content(existing.content)
            if payload is not None:
                return {"generated": False, "digest": payload, "date": date_str}

    # 当天全部对话（时间正序）。
    # ⚠️ 必须排除 role='summary' 的对话压缩记录：那是系统生成的第三人称摘要，
    # 不是老人/助手说的话。不排除会同时造成两个问题——
    # ① 统计被污染：时段跨度把早上的压缩记录算进来，显得老人"从早聊到晚"，
    #    实际可能只有下午聊了几句；
    # ② 摘要输入被污染：模型看到"助手: 王奶奶今天天气好时外出散步…"这种
    #    第三人称总结，会和原文重复且容易混淆，诱发编造。
    day_end = day_start + timedelta(days=1)
    conv_stmt = (
        select(Conversation)
        .where(
            Conversation.user_id == elderly_user_id,
            Conversation.created_at >= day_start,
            Conversation.created_at < day_end,
            Conversation.role != "summary",
        )
        .order_by(Conversation.id)
    )
    convs = list((await session.execute(conv_stmt)).scalars().all())

    memoir = await _memoir_counts(session, elderly_user_id, day_start)
    # 既没聊过、也没有新的可见回忆 → 今天没有可报的
    if not convs and not memoir["today"]:
        return None

    prof = (await session.execute(
        select(ElderlyProfile.name).where(ElderlyProfile.user_id == elderly_user_id)
    )).scalar_one_or_none()
    elderly_name = prof or "老人家"

    payload = await build_digest_payload(elderly_name, convs, date_str, memoir=memoir)
    content = json.dumps(payload, ensure_ascii=False)

    family_ids = await FamilyRepo(session).list_family(elderly_user_id)
    if family_ids:
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
        await session.commit()

    return {"generated": True, "digest": payload, "date": date_str}


async def daily_digest_job() -> None:
    """每日陪伴日报推送（定时，默认每天 20:30）。"""
    logger.info("执行每日陪伴日报任务")
    day_start, day_end = _today_range()
    date_str = day_start.strftime("%Y-%m-%d")

    async with get_session_factory()() as session:
        # 有动静 = 聊过天 ∪ 今天留档了回忆。合并去重后再逐个处理，
        # 这样"今天没怎么聊天但认真讲了一段往事"的日子也有日报。
        active = await _list_today_active_elderly(session, day_start, day_end)
        archived = await _list_today_archived_elderly(session, day_start)
        elderly_ids = list(dict.fromkeys(active + archived))
        if not elderly_ids:
            logger.info("今天没有聊天记录也没有新回忆，跳过日报生成")
            return

        pushed = 0
        for elderly_user_id in elderly_ids:
            result = await generate_digest_for(session, elderly_user_id, day_start, date_str)
            if result is None:
                continue
            if result["generated"]:
                pushed += 1
            else:
                logger.info("老人 %s 今日日报已生成，跳过", elderly_user_id)

        await session.commit()
        logger.info("每日陪伴日报完成：%d 位老人，新推送 %d 条", len(elderly_ids), pushed)
