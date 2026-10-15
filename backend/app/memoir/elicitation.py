"""M4 缺口追问决策层（回忆录的成败关键）。

这一层要解决的不是"怎么问"，而是**要不要问**。老人陪伴产品里，
一个不合时宜的追问比不问伤害大得多——老人会觉得"这机器在查我"。
所以这里的默认答案是 **不问**，只有明确的绿灯才放行。

**三道硬门禁**（任一不满足 → 直接 None，没有例外）：

| 门禁 | 条件 | 为什么 |
|---|---|---|
| 风险 | `risk_level != "low"` | 老人正难过/焦虑/有风险时追问往事，是最糟的时机 |
| 会话上限 | 本会话已问满 `memoir_max_asks_per_session` | 一晚上被问三回，就成了调查问卷 |
| 候选 | 没有过 cooldown 的缺口 | 刚问过又问，是唠叨 |

**三个正向信号**（至少命中一个才放行，不是"满足即可问"而是"有理由才问"）：

- `day_opening` —— 当天第一句开场，老人本来就要起话头
- `paused`      —— 老人回复明显变短且情绪平稳，是自然停顿
- `relevant`    —— 正好聊到那条故事的时代/地点/人物，顺带一问最自然

**「本会话」的定义**：以 `SESSION_IDLE_MINUTES` 为界的连续聊天窗口。
用「最近 N 分钟内问过几次」判定，而不是自然日——老人上午聊完、下午又来，
那是两段对话，不该因为"今天已经问过"就被封口一整天。

契约3（主动追问但克制）：本模块是唯一决定"要不要问"的地方，
所有门禁都返回 None 而不是降级为"换个更弱的问法"。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Sequence

from sqlalchemy import select

from app.db.models import Conversation, LifeStory, StoryElicitationQueue

logger = logging.getLogger(__name__)

# 一次连续聊天的空闲边界：超过这个时长没说话，就当作新一段对话
SESSION_IDLE_MINUTES = 30

# 同一缺口最多问几次（问满即 abandoned，对应「同问题 2 次无回应 → 放弃」）
MAX_ASKS_PER_GAP = 2

# 追问后的冷却天数
DEFAULT_COOLDOWN_DAYS = 3

# "回复变短"的判定：本轮字数 ≤ 近期平均的 60%
PAUSED_LEN_RATIO = 0.6
# "情绪平稳"的判定：强度低于此值才认为适合追问
PAUSED_MAX_INTENSITY = 0.5

# 老人明确表示不想谈的信号（回避处理，保守起见只认这些明确说法）
AVOIDANCE_MARKERS = (
    "不想说", "不想提", "别提了", "不说了", "别问了", "过去的事别提",
    "没什么好说", "算了不说", "不愿意说", "别问这个", "不想回忆",
)


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GapCandidate:
    """一条候选缺口 + 它所属故事的相关信息（供"顺带一问"判定）。"""

    gap_id: int
    story_id: int
    question: str            # 追问方向（模板），交给主模型改写成自然问句
    gap_type: str
    priority: float
    story_title: str = ""
    era_tags: tuple[str, ...] = ()
    place: str = ""
    people: tuple[str, ...] = ()


@dataclass(frozen=True)
class TurnSignals:
    """本轮对话的可观测信号。全部由调用方（MemoryManager）算好传进来。"""

    risk_level: str = "low"
    current_len: int = 0
    recent_user_len_avg: float = 0.0
    emotion_intensity: float = 0.0
    topic: str = ""
    is_first_turn_of_day: bool = False
    session_asks: int = 0
    max_asks_per_session: int = 1


@dataclass(frozen=True)
class ElicitationDecision:
    """放行结果。带 `triggers` / `reason` 是为了可观测——上线后要能回答
    "为什么昨天问了那一句"。"""

    gap_id: int
    story_id: int
    gap_type: str
    hint: str
    triggers: tuple[str, ...] = ()
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "gap_id": self.gap_id,
            "story_id": self.story_id,
            "gap_type": self.gap_type,
            "hint": self.hint,
            "triggers": list(self.triggers),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SessionInfo:
    """本会话的追问计数（含起点，便于日志对照）。"""

    asks: int = 0
    since: Optional[datetime] = None
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 正向信号判定（纯函数）
# ---------------------------------------------------------------------------

def _is_paused(s: TurnSignals) -> bool:
    """对话自然停顿：老人回复明显变短，且情绪平稳。

    没有历史（avg == 0）时判定不成立——无从比较就不猜。
    """
    if s.recent_user_len_avg <= 0 or s.current_len <= 0:
        return False
    return (
        s.current_len <= s.recent_user_len_avg * PAUSED_LEN_RATIO
        and s.emotion_intensity < PAUSED_MAX_INTENSITY
    )


def _is_relevant(candidate: GapCandidate, topic: str) -> bool:
    """正好聊到相关话题：当前话题与该故事的时代/地点/人物/标题互相包含。"""
    if not topic:
        return False
    haystack = [candidate.story_title, candidate.place, *candidate.era_tags, *candidate.people]
    for text in haystack:
        if not text:
            continue
        if topic in text or text in topic:
            return True
    return False


def matched_triggers(candidate: GapCandidate, signals: TurnSignals) -> list[str]:
    """命中的正向信号（顺序固定，便于日志与测试比对）。"""
    hits: list[str] = []
    if signals.is_first_turn_of_day:
        hits.append("day_opening")
    if _is_relevant(candidate, signals.topic):
        hits.append("relevant")
    if _is_paused(signals):
        hits.append("paused")
    return hits


def gate_blocked(
    signals: TurnSignals, candidate: Optional[GapCandidate]
) -> Optional[str]:
    """返回第一道未通过的门禁名；全通过返回 None。

    顺序按"越早否决越省事"排：风险 > 会话上限 > 候选。
    """
    if signals.risk_level != "low":
        return "risk_level"
    if signals.session_asks >= max(1, signals.max_asks_per_session):
        return "session_limit"
    if candidate is None:
        return "no_candidate"
    return None


def should_elicit(
    candidate: Optional[GapCandidate], signals: TurnSignals
) -> Optional[ElicitationDecision]:
    """唯一入口：决定这一轮要不要追问。默认返回 None。"""
    blocked = gate_blocked(signals, candidate)
    if blocked is not None:
        logger.debug("追问被门禁拦下：%s（user 信号 risk=%s asks=%s）",
                     blocked, signals.risk_level, signals.session_asks)
        return None
    assert candidate is not None  # gate 已保证
    triggers = matched_triggers(candidate, signals)
    if not triggers:
        return None
    reason = (
        f"触发 {'+'.join(triggers)}｜{candidate.gap_type}｜优先级 {candidate.priority:.2f}"
    )
    return ElicitationDecision(
        gap_id=candidate.gap_id,
        story_id=candidate.story_id,
        gap_type=candidate.gap_type,
        hint=candidate.question,
        triggers=tuple(triggers),
        reason=reason,
    )


def detect_avoidance(message: str) -> bool:
    """老人是否明确表示不想谈这件事。

    故意做得**保守**：只认明确说法，不做情绪推断。
    误判成"回避"会让一段好好的回忆被永久锁成 private，代价太高。
    """
    text = str(message or "")
    return any(marker in text for marker in AVOIDANCE_MARKERS)


# ---------------------------------------------------------------------------
# 与数据库打交道的部分
# ---------------------------------------------------------------------------

async def session_asks(
    session, elderly_user_id: str, *, now: Optional[datetime] = None
) -> int:
    """本会话已经追问过几次（最近 SESSION_IDLE_MINUTES 分钟内）。"""
    from app.repositories.story_repo import ElicitationRepo

    now = now or datetime.now()
    since = now - timedelta(minutes=SESSION_IDLE_MINUTES)
    return await ElicitationRepo(session).count_asked_since(elderly_user_id, since)


async def last_user_turn_at(
    session, elderly_user_id: str
) -> Optional[datetime]:
    """上一条老人消息的时间。用于判断「今天是否第一次开口」。"""
    stmt = (
        select(Conversation.created_at)
        .where(Conversation.user_id == elderly_user_id, Conversation.role == "user")
        .order_by(Conversation.id.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def is_first_turn_of_day(last_at: Optional[datetime], *, now: Optional[datetime] = None) -> bool:
    """上一条老人消息不是今天 → 本轮是今天第一次开口。"""
    now = now or datetime.now()
    if last_at is None:
        return True
    return last_at.date() < now.date()


async def pick_candidate(
    session, elderly_user_id: str, *, now: Optional[datetime] = None
) -> Optional[GapCandidate]:
    """取优先级最高、且已过 cooldown 的一条缺口（连带它的故事信息）。"""
    from app.repositories.story_repo import ElicitationRepo

    rows = await ElicitationRepo(session).list_candidates(elderly_user_id, now, limit=5)
    if not rows:
        return None
    top = rows[0]
    story = (await session.execute(
        select(LifeStory).where(LifeStory.id == top.story_id)
    )).scalar_one_or_none()
    # 故事被老人弃用/删掉后，缺口不该再问
    if story is None or story.status == "discarded" or story.avoid_flag:
        return None
    return GapCandidate(
        gap_id=top.id,
        story_id=top.story_id,
        question=top.question or "",
        gap_type=top.gap_type or "missing_detail",
        priority=float(top.priority or 0.0),
        story_title=story.title or "",
        era_tags=tuple(story.era_tags or []),
        place=story.place or "",
        people=tuple(story.people or []),
    )


async def build_signals(
    session,
    elderly_user_id: str,
    *,
    risk_level: str,
    current_len: int,
    recent_user_len_avg: float,
    emotion_intensity: float,
    topic: str,
    max_asks_per_session: int,
    now: Optional[datetime] = None,
) -> TurnSignals:
    """把 DB 侧的事实补齐成完整的 TurnSignals。"""
    asks = await session_asks(session, elderly_user_id, now=now)
    first_today = is_first_turn_of_day(
        await last_user_turn_at(session, elderly_user_id), now=now
    )
    return TurnSignals(
        risk_level=risk_level,
        current_len=current_len,
        recent_user_len_avg=recent_user_len_avg,
        emotion_intensity=emotion_intensity,
        topic=topic,
        is_first_turn_of_day=first_today,
        session_asks=asks,
        max_asks_per_session=max_asks_per_session,
    )


async def commit_ask(
    session, decision: ElicitationDecision, *, now: Optional[datetime] = None,
    cooldown_days: int = DEFAULT_COOLDOWN_DAYS,
) -> str:
    """真正问了之后才记账。返回缺口新状态（asked / abandoned）。

    **必须在生成成功之后调用**——生成失败就没问出口，不能占用会话额度，
    否则老人一晚上都等不到那个问题。
    """
    from app.repositories.story_repo import ElicitationRepo

    status = await ElicitationRepo(session).mark_asked(
        decision.gap_id, now=now, cooldown_days=cooldown_days, max_asks=MAX_ASKS_PER_GAP
    )
    logger.info("缺口追问记账 gap=%s story=%s → %s（%s）",
                decision.gap_id, decision.story_id, status, decision.reason)
    return status


async def apply_avoidance(
    session, story_id: int, *, now: Optional[datetime] = None
) -> bool:
    """老人回避了某个话题：标记 avoid + 强制 private 并锁定，并放弃其缺口。

    契约2 + 「永久尊重」：这里一旦落下，任何接口都改不回来。
    """
    from app.repositories.story_repo import ElicitationRepo, StoryRepo

    ok = await StoryRepo(session).mark_avoid(story_id)
    if ok:
        await ElicitationRepo(session).mark_answered(story_id=story_id)
        logger.info("老人回避话题，已永久尊重 story=%s（private + locked）", story_id)
    return ok


async def resolve_gaps_for_story(session, story_id: int) -> int:
    """故事被补充了新信息（老人又说了一段）→ 未终结的缺口标 answered。

    避免"老人已经讲清楚了、机器还在问"这种最伤好感的情况。
    """
    from app.repositories.story_repo import ElicitationRepo

    return await ElicitationRepo(session).mark_answered(story_id=story_id)


# ---------------------------------------------------------------------------
# 账本收口：问完就答了 → 别再问
# ---------------------------------------------------------------------------

def filled_gap_types(extraction: dict) -> set[str]:
    """这一轮提取里，哪些缺口类型被填上了。

    只认"真的给出了值"——时间是空串不算填上，免得把缺口误关了。
    """
    filled: set[str] = set()
    if (extraction.get("time") or {}).get("value"):
        filled.add("missing_time")
    if extraction.get("place"):
        filled.add("missing_place")
    if extraction.get("people"):
        filled.add("missing_person")
    return filled


async def recently_asked_gap(
    session, elderly_user_id: str, *, now: Optional[datetime] = None
):
    """本会话最近被问过的那条缺口（没有则 None）。"""
    now = now or datetime.now()
    since = now - timedelta(minutes=SESSION_IDLE_MINUTES)
    stmt = (
        select(StoryElicitationQueue)
        .where(
            StoryElicitationQueue.elderly_user_id == elderly_user_id,
            StoryElicitationQueue.asked_at.is_not(None),
            StoryElicitationQueue.asked_at >= since,
        )
        .order_by(StoryElicitationQueue.asked_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def close_asked_gaps(
    session, elderly_user_id: str, extraction: dict
) -> int:
    """老人刚把某类信息说清楚了 → 关掉「最近问过的那条故事」里同类缺口。

    只关**同类**：问了时间、老人补了地点，时间缺口还得留着。
    """
    from app.repositories.story_repo import ElicitationRepo

    filled = filled_gap_types(extraction)
    if not filled:
        return 0
    recent = await recently_asked_gap(session, elderly_user_id)
    if recent is None:
        return 0
    rows = await ElicitationRepo(session).for_story(recent.story_id)
    closed = 0
    for gap in rows:
        if gap.gap_type in filled and gap.status in ("pending", "asked"):
            gap.status = "answered"
            closed += 1
    if closed:
        logger.info("老人补上了 %s，关闭缺口 %d 个（story=%s）",
                    "/".join(sorted(filled)), closed, recent.story_id)
    return closed


# ---------------------------------------------------------------------------
# 给 MemoryManager / chat 路由的一站式入口（自己管 session，调用方无感）
# ---------------------------------------------------------------------------

async def preview_for_turn(
    elderly_user_id: str,
    *,
    risk_level: str,
    current_len: int,
    recent_user_len_avg: float,
    emotion_intensity: float,
    topic: str,
    max_asks_per_session: int,
) -> Optional[ElicitationDecision]:
    """对话中途算一次"这轮该不该问"。**只读，不记账。**

    记账发生在生成成功之后（`finalize_turn`）——否则生成失败时额度已经被占掉，
    老人这一晚上就再也等不到那个问题了。

    任何异常都静默降级为"不问"：追问是锦上添花，绝不能让主线聊天挂掉。
    """
    from app.db.base import get_session_factory

    try:
        async with get_session_factory()() as session:
            signals = await build_signals(
                session,
                elderly_user_id,
                risk_level=risk_level,
                current_len=current_len,
                recent_user_len_avg=recent_user_len_avg,
                emotion_intensity=emotion_intensity,
                topic=topic,
                max_asks_per_session=max_asks_per_session,
            )
            candidate = await pick_candidate(session, elderly_user_id)
            return should_elicit(candidate, signals)
    except Exception:
        logger.exception("追问决策失败，本轮降级为不追问 user=%s", elderly_user_id)
        return None


async def finalize_turn(
    elderly_user_id: str,
    message: str,
    decision: Optional[ElicitationDecision],
    *,
    cooldown_days: int = DEFAULT_COOLDOWN_DAYS,
) -> dict:
    """生成**成功之后**的回忆录收尾，一个 session 内做完两件事：

    1. 老人明确说不想谈 → 对最近问过的那条故事永久尊重（private + 锁定）；
    2. 这一轮确实问出口了 → 记账（ask_count / cooldown_until / 必要时 abandoned）。

    放在生成之后是刻意的：生成失败就没问出口，不该占用会话额度。
    整体失败也只记日志，绝不回抛——追问出问题不能影响已经发出去的回复。
    """
    from app.db.base import get_session_factory
    from app.repositories.story_repo import StoryRepo

    result: dict = {"avoided_story": None, "gap_status": None}
    try:
        async with get_session_factory()() as session:
            if detect_avoidance(message):
                recent = await recently_asked_gap(session, elderly_user_id)
                if recent is not None:
                    await StoryRepo(session).mark_avoid(recent.story_id)
                    await resolve_gaps_for_story(session, recent.story_id)
                    result["avoided_story"] = recent.story_id

            if decision is not None:
                result["gap_status"] = await commit_ask(
                    session, decision, cooldown_days=cooldown_days
                )
            # 无论有没有追问，回避处理都必须落盘
            await session.commit()
    except Exception:
        logger.exception("回忆录收尾失败 user=%s", elderly_user_id)
    return result
