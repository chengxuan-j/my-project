"""夜间缺口扫描（M4）。

每天凌晨（默认 01:30，早于 02:00 的记忆整合）把补充缺口队列算一遍账，
让白天的对话路径只需要做一次很轻的读。

做三件事：

1. **冷却到期放回**：`asked` 且 `cooldown_until` 已过的缺口 → `pending`。
   状态账本保持干净，白天不必再判"是不是借 cooldown 混进来的"。
2. **已经知道的就不再问**：故事已经被老人补齐了 `time_value` / `place` /
   `people`，对应缺口直接 `answered`。这是最容易伤好感的一类误问——老人昨天
   明明说了是哪一年，今天机器还问"那是哪一年来着？"。
3. **过期放弃**：`pending` 坐了太久（默认 30 天）还没问上的缺口 → `abandoned`。
   老人当时那句话头早凉了，隔一个月再拎出来只会显得莫名其妙。

关于设计文档里"夜间把候选算好，避免对话中现算（性能）"：

**没有采用快照表**。实测白天的一次预选是 2 次走索引的小查询
（`life_stories` 按 user 取一条 + `story_elicitation_queue` 按
`(user, status, cooldown_until)` 复合索引取一条），在演示规模上是亚毫秒级；
为它引入一张快照表 + 失效逻辑，复杂度远大于收益，还会引入"快照过期导致
同一个问题被问两次"的新风险。这里改为**把候选清单打进日志**（运维可读），
真正的性能闸门是 `MEMOIR_ENABLED` 开关与 `risk_level == "low"` 短路。
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from app.config import get_settings
from app.db.base import get_session_factory
from app.db.models import LifeStory, StoryElicitationQueue

logger = logging.getLogger(__name__)

# pending 缺口最多等多少天还没问上就放弃
STALE_PENDING_DAYS = 30

# 缺口类型 → 故事上对应的字段是否已经填上（填上就不必再问）
_GAP_FILLED_BY = {
    "missing_time": lambda s: bool(s.time_value),
    "missing_place": lambda s: bool(s.place),
    "missing_person": lambda s: bool(s.people),
}


async def story_gap_scan_job() -> None:
    """夜间缺口扫描主流程。幂等：重复执行结果一致。"""
    settings = get_settings()
    if not settings.memoir_enabled:
        logger.info("MEMOIR_ENABLED 未开，跳过夜间缺口扫描")
        return

    now = datetime.now()
    aged, released, filled, candidates = 0, 0, 0, {}

    async with get_session_factory()() as session:
        # 1. 冷却到期 → 放回 pending
        expired = (await session.execute(
            select(StoryElicitationQueue).where(
                StoryElicitationQueue.status == "asked",
                StoryElicitationQueue.cooldown_until.is_not(None),
                StoryElicitationQueue.cooldown_until <= now,
            )
        )).scalars().all()
        for gap in expired:
            gap.status = "pending"
            released += 1

        # 2. 故事已补齐 → 关闭对应缺口
        gaps = (await session.execute(
            select(StoryElicitationQueue).where(
                StoryElicitationQueue.status.in_(("pending", "asked"))
            )
        )).scalars().all()
        story_ids = {g.story_id for g in gaps}
        stories = {}
        if story_ids:
            rows = (await session.execute(
                select(LifeStory).where(LifeStory.id.in_(story_ids))
            )).scalars().all()
            stories = {s.id: s for s in rows}

        stale_cutoff = now - timedelta(days=STALE_PENDING_DAYS)
        for gap in gaps:
            story = stories.get(gap.story_id)
            # 故事被弃用/回避过 → 缺口一律作废
            if story is None or story.status == "discarded" or story.avoid_flag:
                gap.status = "abandoned"
                continue
            checker = _GAP_FILLED_BY.get(gap.gap_type)
            if checker is not None and checker(story):
                gap.status = "answered"
                filled += 1
                continue
            # 3. 坐了太久还没问上 → 放弃
            if gap.created_at and gap.created_at < stale_cutoff:
                gap.status = "abandoned"
                aged += 1

        await session.commit()

        # 给运维留一份"明天可以问谁什么"，同时验证候选查询确实可用
        remaining = (await session.execute(
            select(StoryElicitationQueue).where(
                StoryElicitationQueue.status == "pending",
                StoryElicitationQueue.cooldown_until.is_(None),
            )
        )).scalars().all()
        for gap in remaining:
            top = candidates.get(gap.elderly_user_id)
            if top is None or (gap.priority or 0) > (top.priority or 0):
                candidates[gap.elderly_user_id] = gap

    for user_id, gap in sorted(candidates.items()):
        logger.info(
            "明日可追问 user=%s %s（优先级 %.2f）：%s",
            user_id, gap.gap_type, gap.priority or 0.0, (gap.question or "")[:40],
        )
    logger.info(
        "夜间缺口扫描完成：冷却放回 %d，已补齐关闭 %d，过期放弃 %d，待问候选人 %d",
        released, filled, aged, len(candidates),
    )
