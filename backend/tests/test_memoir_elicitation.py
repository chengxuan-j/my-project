"""M4 缺口追问测试。

分三层：
1. 门禁与信号（纯函数）——三道 `None` 条件是契约3 的硬约束，必须逐条覆盖；
2. 账本（DB）——cooldown、会话计数、问满放弃、补齐即关闭；
3. 收尾（DB + prompt）——回避永久尊重、提示词块只在该问时注入。

不依赖 LLM Key。
"""
import os
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "test-secret"

import pytest  # noqa: E402

from app.db.base import dispose_engine, get_session_factory, init_async_db  # noqa: E402
from app.db.models import Conversation, LifeStory  # noqa: E402
from app.memoir import elicitation as E  # noqa: E402
from app.repositories.story_repo import ElicitationRepo, StoryRepo  # noqa: E402


def _candidate(**kw) -> E.GapCandidate:
    defaults = dict(
        gap_id=1, story_id=10, question="那是哪一年的事？",
        gap_type="missing_time", priority=0.8,
        story_title="纺织厂", era_tags=("知青年代",), place="纺织厂",
        people=("老王",),
    )
    defaults.update(kw)
    return E.GapCandidate(**defaults)


def _signals(**kw) -> E.TurnSignals:
    defaults = dict(
        risk_level="low", current_len=30, recent_user_len_avg=30.0,
        emotion_intensity=0.2, topic="随便聊聊", is_first_turn_of_day=True,
        session_asks=0, max_asks_per_session=1,
    )
    defaults.update(kw)
    return E.TurnSignals(**defaults)


# ---------------------------------------------------------------------------
# 1. 三道硬门禁（契约3）
# ---------------------------------------------------------------------------

def test_gate_risk_level_blocks():
    """老人情绪不好时绝对不追问——这是最不能错的一条。"""
    assert E.should_elicit(_candidate(), _signals(risk_level="high")) is None
    assert E.should_elicit(_candidate(), _signals(risk_level="medium")) is None
    assert E.gate_blocked(_signals(risk_level="high"), _candidate()) == "risk_level"


def test_gate_session_limit_blocks():
    s = _signals(session_asks=1, max_asks_per_session=1)
    assert E.should_elicit(_candidate(), s) is None
    assert E.gate_blocked(s, _candidate()) == "session_limit"
    # 上限放宽后可以问
    assert E.should_elicit(_candidate(), _signals(session_asks=1, max_asks_per_session=2))


def test_gate_no_candidate_blocks():
    assert E.should_elicit(None, _signals()) is None
    assert E.gate_blocked(_signals(), None) == "no_candidate"


def test_gate_zero_max_still_allows_one():
    """上限配成 0 不该把功能变成死的——按最小 1 处理。"""
    assert E.should_elicit(_candidate(), _signals(max_asks_per_session=0)) is not None


# ---------------------------------------------------------------------------
# 2. 正向信号：一个都不命中就不问
# ---------------------------------------------------------------------------

def test_no_trigger_means_no_ask():
    """门禁全过、但没有任何正向理由 → 仍然不问（默认是不问）。"""
    s = _signals(is_first_turn_of_day=False, topic="今天天气不错", current_len=30,
                 recent_user_len_avg=30.0)
    assert E.should_elicit(_candidate(), s) is None


def test_trigger_day_opening():
    d = E.should_elicit(_candidate(), _signals())
    assert d is not None and d.triggers == ("day_opening",)


def test_trigger_relevant_when_topic_mention_era_or_place():
    s = _signals(is_first_turn_of_day=False, topic="纺织厂")
    d = E.should_elicit(_candidate(), s)
    assert d is not None and "relevant" in d.triggers


def test_trigger_paused_needs_short_reply_and_calm():
    base = dict(is_first_turn_of_day=False, topic="嗯", recent_user_len_avg=40.0)
    # 回复变短 + 情绪平稳 → 命中
    d = E.should_elicit(_candidate(), _signals(current_len=10, emotion_intensity=0.2, **base))
    assert d is not None and "paused" in d.triggers
    # 回复变短但情绪激动 → 不命中（老人在气头上，不是停顿）
    assert E.should_elicit(
        _candidate(), _signals(current_len=10, emotion_intensity=0.9, **base)
    ) is None
    # 回复不短 → 不命中
    assert E.should_elicit(
        _candidate(), _signals(current_len=40, emotion_intensity=0.2, **base)
    ) is None


def test_trigger_paused_no_history_no_guess():
    """没有历史基线就不猜"变短了"——宁可不问。"""
    assert E._is_paused(_signals(current_len=5, recent_user_len_avg=0.0)) is False


def test_decision_reason_is_observable():
    d = E.should_elicit(_candidate(), _signals())
    assert d is not None
    assert "day_opening" in d.reason and "missing_time" in d.reason
    assert d.hint == "那是哪一年的事？"
    assert d.as_dict()["gap_id"] == 1


# ---------------------------------------------------------------------------
# 3. 回避识别（保守）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "过去的事别提了", "我不想说这个", "别问了", "算了不说了", "不想回忆那些",
])
def test_detect_avoidance_positive(text):
    assert E.detect_avoidance(text) is True


@pytest.mark.parametrize("text", [
    "今天天气不错", "我有点难过", "那时候挺苦的", "想不起来具体哪年了", "",
])
def test_detect_avoidance_negative(text):
    """误判成"回避"会把一段好回忆永久锁成 private，代价太高，所以只认明确说法。"""
    assert E.detect_avoidance(text) is False


# ---------------------------------------------------------------------------
# 4. 账本（DB）
# ---------------------------------------------------------------------------

async def _bootstrap():
    await dispose_engine()
    await init_async_db()


async def _seed_story(user_id: str, **kw) -> int:
    async with get_session_factory()() as session:
        defaults = dict(status="archived", title="纺织厂的第一天", summary="十八岁进纺织厂。")
        defaults.update(kw)
        story = await StoryRepo(session).create(user_id, **defaults)
        await session.commit()
        return story.id


async def _seed_gap(user_id: str, story_id: int, **kw) -> int:
    async with get_session_factory()() as session:
        defaults = dict(question="那是哪一年？", gap_type="missing_time", priority=0.8)
        defaults.update(kw)
        gap = await ElicitationRepo(session).add(user_id, story_id, **defaults)
        await session.commit()
        return gap.id


@pytest.mark.asyncio
async def test_pick_candidate_skips_cooldown():
    await _bootstrap()
    story_id = await _seed_story("m4_u1")
    now = datetime.now()
    gap_id = await _seed_gap("m4_u1", story_id)

    async with get_session_factory()() as session:
        # 刚问过、冷却中 → 不候选
        await ElicitationRepo(session).mark_asked(gap_id, now=now, cooldown_days=3)
        await session.commit()
        assert await E.pick_candidate(session, "m4_u1", now=now) is None
        # 冷却过了 → 又成为候选
        later = now + timedelta(days=4)
        cand = await E.pick_candidate(session, "m4_u1", now=later)
        assert cand is not None and cand.gap_id == gap_id


@pytest.mark.asyncio
async def test_pick_candidate_skips_discarded_or_avoided_story():
    await _bootstrap()
    story_id = await _seed_story("m4_u2", status="discarded")
    await _seed_gap("m4_u2", story_id)
    async with get_session_factory()() as session:
        assert await E.pick_candidate(session, "m4_u2") is None

    await _bootstrap()
    story_id = await _seed_story("m4_u3")
    await _seed_gap("m4_u3", story_id)
    async with get_session_factory()() as session:
        await StoryRepo(session).mark_avoid(story_id)   # 老人回避过
        await session.commit()
        assert await E.pick_candidate(session, "m4_u3") is None


@pytest.mark.asyncio
async def test_session_asks_counts_recent_window():
    await _bootstrap()
    story_id = await _seed_story("m4_u4")
    gap_id = await _seed_gap("m4_u4", story_id)
    async with get_session_factory()() as session:
        assert await E.session_asks(session, "m4_u4") == 0
        await ElicitationRepo(session).mark_asked(gap_id, cooldown_days=3)
        await session.commit()
        assert await E.session_asks(session, "m4_u4") == 1
        # 40 分钟后再看：那段对话已经结束，不算本会话
        assert await E.session_asks(
            session, "m4_u4", now=datetime.now() + timedelta(minutes=40)
        ) == 0


@pytest.mark.asyncio
async def test_mark_asked_abandons_on_second_ask():
    """同问题 2 次无回应 → abandoned，不再缠着老人。"""
    await _bootstrap()
    story_id = await _seed_story("m4_u5")
    gap_id = await _seed_gap("m4_u5", story_id)
    async with get_session_factory()() as session:
        repo = ElicitationRepo(session)
        assert await repo.mark_asked(gap_id) == "asked"
        assert await repo.mark_asked(gap_id) == "abandoned"
        await session.commit()
        gap = (await repo.for_story(story_id))[0]
        assert gap.ask_count == 2
        assert await E.pick_candidate(session, "m4_u5") is None


@pytest.mark.asyncio
async def test_close_asked_gaps_only_same_type():
    """问了时间、老人补了地点 → 时间缺口必须留着，别一起关掉。"""
    await _bootstrap()
    story_id = await _seed_story("m4_u6")
    await _seed_gap("m4_u6", story_id, gap_type="missing_time", priority=0.8)
    await _seed_gap("m4_u6", story_id, gap_type="missing_place", priority=0.65)
    async with get_session_factory()() as session:
        # 先"问过"，这样 close_asked_gaps 才认得这是最近问的那条
        cand = await E.pick_candidate(session, "m4_u6")
        assert cand is not None
        await E.commit_ask(session, E.ElicitationDecision(
            gap_id=cand.gap_id, story_id=story_id, gap_type=cand.gap_type,
            hint=cand.question, triggers=("day_opening",),
        ))
        await session.commit()

        closed = await E.close_asked_gaps(
            session, "m4_u6", {"place": "纺织厂", "people": []}
        )
        await session.commit()
        assert closed == 1     # 只关掉地点
        gaps = {g.gap_type: g.status for g in await ElicitationRepo(session).for_story(story_id)}
        assert gaps["missing_place"] == "answered"
        assert gaps["missing_time"] in ("asked", "pending")


@pytest.mark.asyncio
async def test_is_first_turn_of_day():
    await _bootstrap()
    now = datetime.now()
    assert E.is_first_turn_of_day(None, now=now) is True
    assert E.is_first_turn_of_day(now - timedelta(days=1), now=now) is True
    assert E.is_first_turn_of_day(now, now=now) is False


@pytest.mark.asyncio
async def test_last_user_turn_reads_elderly_only():
    await _bootstrap()
    async with get_session_factory()() as session:
        session.add(Conversation(user_id="m4_u7", role="user", content="我十六岁下乡"))
        await session.flush()
        last = await E.last_user_turn_at(session, "m4_u7")
        assert last is not None
        assert await E.last_user_turn_at(session, "nobody") is None


@pytest.mark.asyncio
async def test_finalize_turn_avoidance_locks_story_private():
    """契约2 + 「永久尊重」：老人回避后 private 且锁定，缺口同时作废。"""
    await _bootstrap()
    story_id = await _seed_story("m4_u8")
    gap_id = await _seed_gap("m4_u8", story_id)
    async with get_session_factory()() as session:
        await ElicitationRepo(session).mark_asked(gap_id, cooldown_days=3)
        await session.commit()

    result = await E.finalize_turn("m4_u8", "过去的事别提了", None)
    assert result["avoided_story"] == story_id

    async with get_session_factory()() as session:
        story = await StoryRepo(session).get(story_id)
        assert story.avoid_flag is True
        assert story.visibility == "private"
        assert story.visibility_locked is True
        # 锁定后连仓储都改不动
        assert await StoryRepo(session).set_visibility(story_id, "public") == "locked"
        gaps = await ElicitationRepo(session).for_story(story_id)
        assert all(g.status == "answered" for g in gaps)


@pytest.mark.asyncio
async def test_finalize_turn_without_decision_does_nothing():
    await _bootstrap()
    story_id = await _seed_story("m4_u9")
    gap_id = await _seed_gap("m4_u9", story_id)
    result = await E.finalize_turn("m4_u9", "今天天气不错", None)
    assert result == {"avoided_story": None, "gap_status": None}
    async with get_session_factory()() as session:
        gap = (await ElicitationRepo(session).for_story(story_id))[0]
        assert gap.ask_count == 0 and gap.asked_at is None


@pytest.mark.asyncio
async def test_finalize_turn_commits_ask():
    await _bootstrap()
    story_id = await _seed_story("m4_u10")
    gap_id = await _seed_gap("m4_u10", story_id)
    decision = E.ElicitationDecision(
        gap_id=gap_id, story_id=story_id, gap_type="missing_time",
        hint="那是哪一年？", triggers=("day_opening",),
    )
    result = await E.finalize_turn("m4_u10", "嗯", decision, cooldown_days=3)
    assert result["gap_status"] == "asked"
    async with get_session_factory()() as session:
        gap = (await ElicitationRepo(session).for_story(story_id))[0]
        assert gap.ask_count == 1
        assert gap.asked_at is not None
        assert gap.cooldown_until is not None


@pytest.mark.asyncio
async def test_preview_for_turn_degrades_silently_without_db():
    """库没初始化也不能抛——追问永远只是锦上添花。"""
    await dispose_engine()
    got = await E.preview_for_turn(
        "nobody", risk_level="low", current_len=5, recent_user_len_avg=40.0,
        emotion_intensity=0.1, topic="", max_asks_per_session=1,
    )
    assert got is None


# ---------------------------------------------------------------------------
# 5. 提示词注入
# ---------------------------------------------------------------------------

def test_elicitation_block_only_when_decided():
    from app.companion.prompts import _elicitation_block

    class Ctx:
        elicitation = None
    assert _elicitation_block(Ctx()) == ""

    class Ctx2:
        elicitation = {"hint": "问问他那年多大", "triggers": ["day_opening"],
                       "gap_id": 1, "story_id": 2, "gap_type": "missing_time",
                       "reason": "x"}
    block = _elicitation_block(Ctx2())
    assert "问问他那年多大" in block
    # 必须强调"化成自己的话"，否则每次都是同一句模板
    assert "不要照搬" in block
    # 必须给出"老人不想聊就放下"的出口
    assert "不想提" in block


def test_elicitation_block_empty_hint_skipped():
    from app.companion.prompts import _elicitation_block

    class Ctx:
        elicitation = {"hint": "   "}
    assert _elicitation_block(Ctx()) == ""


def test_build_messages_includes_elicitation():
    from app.companion.prompts import build_messages

    class Profile:
        name = "王阿姨"
        def prompt_block(self):
            return ""

    class Ctx:
        profile = Profile()
        history = []
        current_topic = ""
        emotion = "neutral"
        emotion_intensity = 0.0
        scene = "conversation"
        need = "none"
        decision = None
        long_memories = []
        knowledge_results = []
        safety_directive = ""
        elicitation = {"hint": "问问她进厂第一天的情形"}

    system = build_messages(Ctx(), "嗯")[0]["content"]
    assert "问问她进厂第一天的情形" in system
    assert "【本轮可以顺带问一句往事】" in system
