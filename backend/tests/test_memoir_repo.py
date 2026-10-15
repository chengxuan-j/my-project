"""M1 回忆录仓储与服务编排测试。

不依赖真实 LLM（直接喂归一化后的 extraction dict），覆盖：
- 落库状态流转（draft / pending_confirm）
- 契约2：创伤强制 private + 锁定，且家属不可改回
- 契约5：raw_dialogue 只追加
- 家属可见性过滤（private / 未归档都不可见）
- 缺口检测与排队

注意：与 test_daily_digest.py 一致——DATABASE_URL 指向内存库，每个用例
独立事件循环，避免 async engine 跨 loop 复用连接。
"""
import asyncio
import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "test-secret"

import pytest  # noqa: E402

from app.memoir import story_service  # noqa: E402
from app.memoir.gap_detector import classify_gap, detect_gaps, estimate_completeness  # noqa: E402
from app.repositories.story_repo import (  # noqa: E402
    VIS_LOCKED,
    VIS_NOT_FOUND,
    VIS_OK,
    CompilationRepo,
    ElicitationRepo,
    StoryRepo,
)


@pytest.fixture()
def _db():
    from app.db.base import dispose_engine, get_session_factory, init_async_db

    async def _setup():
        await dispose_engine()
        await init_async_db()

    asyncio.run(_setup())
    return get_session_factory()


def _extraction(**overrides) -> dict:
    """一条"信息齐全"的提取结果，可按需覆盖字段。"""
    base = {
        "is_life_story": True,
        "confidence": 0.85,
        "title": "纺织厂的第一天",
        "summary": "十八岁进纺织厂，第一次听见车间的轰鸣。",
        "time": {"type": "era_anchor", "value": "刚进厂那会儿", "confidence": 0.6},
        "era_tags": ["知青年代"],
        "place": "纺织厂车间",
        "people": ["老师傅（带她的师傅）"],
        "emotion_tone": "怀念",
        "missing": ["具体年份"],
        "follow_up_hint": "可以问问她第一天进车间紧不紧张",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 缺口检测（纯函数）
# ---------------------------------------------------------------------------

def test_classify_gap():
    assert classify_gap("具体年份") == "missing_time"
    assert classify_gap("在哪儿") == "missing_place"
    assert classify_gap("老王的全名") == "missing_person"
    assert classify_gap("后来怎样了") == "missing_detail"


def test_detect_gaps_caps_and_sorts():
    gaps = detect_gaps({
        "confidence": 0.9,
        "missing": ["具体年份", "哪个厂区", "老王的全名", "后来怎样了", "还有什么讲究"],
    })
    assert len(gaps) <= 3                                   # 契约3：不堆问题
    assert gaps[0]["gap_type"] == "missing_time"             # 时间优先级最高
    assert [g["priority"] for g in gaps] == sorted(
        [g["priority"] for g in gaps], reverse=True
    )


def test_detect_gaps_uses_follow_up_hint_for_top_gap():
    gaps = detect_gaps({
        "confidence": 0.8,
        "missing": ["具体年份"],
        "follow_up_hint": "那会儿您走的时候，家里人是啥反应呀？",
    })
    assert gaps[0]["question"] == "那会儿您走的时候，家里人是啥反应呀？"


def test_completeness_bounds():
    assert 0.0 <= estimate_completeness({"missing": []}) <= 1.0
    rich = estimate_completeness(_extraction(missing=[]))
    poor = estimate_completeness({"missing": ["a", "b", "c", "d"]})
    assert rich > poor


# ---------------------------------------------------------------------------
# 服务编排：状态与契约2
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ingest_creates_pending_confirm(_db):
    async with _db() as session:
        story = await story_service.ingest(
            session, "elderly_001", _extraction(), "我八几年当上小组长了。", "那可不轻松。"
        )
        await session.commit()
        assert story is not None
        assert story.status == "pending_confirm"
        assert story.visibility == "family"           # 契约2 默认 family
        assert story.visibility_locked is False
        assert story.era_tags == ["知青年代"]
        assert len(story.raw_dialogue) == 2           # user + assistant


@pytest.mark.asyncio
async def test_ingest_trauma_forces_private_and_locked(_db):
    """契约2：创伤内容强制 private + 锁定。"""
    async with _db() as session:
        story = await story_service.ingest(
            session, "elderly_001",
            _extraction(emotion_tone="创伤", title="老伴走了"),
            "一八年的冬天他走的，走得挺急。", "那份想念不会淡的。",
        )
        await session.commit()
        assert story.visibility == "private"
        assert story.visibility_locked is True


@pytest.mark.asyncio
async def test_ingest_avoided_topic_is_locked(_db):
    async with _db() as session:
        story = await story_service.ingest(
            session, "elderly_001", _extraction(), "……", "", avoided=True
        )
        await session.commit()
        assert story.visibility == "private"
        assert story.visibility_locked is True
        assert story.avoid_flag is True


@pytest.mark.asyncio
async def test_ingest_thin_story_stays_draft(_db):
    """信息太少只进 draft，不主动请老人确认（契约3 克制）。"""
    thin = _extraction(
        title="", summary="", place="", people=[], era_tags=[],
        time={"type": "relative", "value": "", "confidence": 0.0},
        missing=["具体年份", "哪个厂区", "老王的全名", "后来怎样了"],
        emotion_tone="平淡",
    )
    async with _db() as session:
        story = await story_service.ingest(session, "elderly_001", thin, "那时候挺好的。", "")
        await session.commit()
        assert story.status == "draft"


@pytest.mark.asyncio
async def test_ingest_ignores_non_story(_db):
    async with _db() as session:
        assert await story_service.ingest(
            session, "elderly_001", {"is_life_story": False}, "今天天气不错", ""
        ) is None


@pytest.mark.asyncio
async def test_ingest_enqueues_gaps(_db):
    async with _db() as session:
        story = await story_service.ingest(
            session, "elderly_001",
            _extraction(missing=["具体年份", "哪个厂区", "老王的全名"]),
            "那年我进厂了。", "",
        )
        await session.commit()
        gaps = await ElicitationRepo(session).for_story(story.id)
        assert len(gaps) == 3
        assert all(g.status == "pending" for g in gaps)
        assert {g.gap_type for g in gaps} == {
            "missing_time", "missing_place", "missing_person"
        }


# ---------------------------------------------------------------------------
# 契约2 / 契约5：仓储层强制点
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_visibility_locked_cannot_be_changed(_db):
    async with _db() as session:
        repo = StoryRepo(session)
        story = await story_service.ingest(
            session, "elderly_001", _extraction(emotion_tone="创伤"), "他走了。", ""
        )
        await session.commit()

        # 改回 family 必须被拒绝（家属不可改回）
        assert await repo.set_visibility(story.id, "family") == VIS_LOCKED
        await session.commit()
        assert (await repo.get(story.id)).visibility == "private"

        assert await repo.set_visibility(999999, "family") == VIS_NOT_FOUND


@pytest.mark.asyncio
async def test_visibility_change_allowed_when_not_locked(_db):
    async with _db() as session:
        repo = StoryRepo(session)
        story = await story_service.ingest(session, "elderly_001", _extraction(), "往事。", "")
        await session.commit()
        assert await repo.set_visibility(story.id, "private") == VIS_OK
        await session.commit()
        assert (await repo.get(story.id)).visibility == "private"


@pytest.mark.asyncio
async def test_append_raw_is_append_only(_db):
    """契约5：原文只增不改——已有片段既不修改也不删除，重复自动跳过。"""
    async with _db() as session:
        repo = StoryRepo(session)
        story = await story_service.ingest(session, "elderly_001", _extraction(), "用户原话", "助手回复")
        await session.commit()

        before = list(story.raw_dialogue)
        await repo.append_raw(story.id, [{"role": "user", "content": "用户原话"}])  # 重复
        await session.commit()
        assert (await repo.get(story.id)).raw_dialogue == before   # 未变化

        await repo.append_raw(story.id, [{"role": "user", "content": "补充的一句话"}])
        await session.commit()
        after = (await repo.get(story.id)).raw_dialogue
        assert after[:len(before)] == before                        # 前缀完全保留
        assert len(after) == len(before) + 1


# ---------------------------------------------------------------------------
# 家属可见性过滤
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_family_sees_only_archived_and_visible(_db):
    async with _db() as session:
        repo = StoryRepo(session)

        archived_family = await repo.create("elderly_001", title="可看", status="archived",
                                            visibility="family")
        archived_public = await repo.create("elderly_001", title="公开", status="archived",
                                            visibility="public")
        await repo.create("elderly_001", title="未确认", status="pending_confirm",
                          visibility="family")
        await repo.create("elderly_001", title="创伤", status="archived",
                          visibility="private", visibility_locked=True)
        await repo.create("other_elder", title="别人家的", status="archived",
                          visibility="family")
        await session.commit()

        visible = await repo.list_visible_for_family("elderly_001")
        titles = {s.title for s in visible}
        assert titles == {"可看", "公开"}
        assert archived_public.id in {s.id for s in visible}
        assert archived_family.id in {s.id for s in visible}


@pytest.mark.asyncio
async def test_count_by_status(_db):
    async with _db() as session:
        repo = StoryRepo(session)
        await repo.create("elderly_001", status="draft")
        await repo.create("elderly_001", status="draft")
        await repo.create("elderly_001", status="archived")
        await session.commit()
        assert await repo.count_by_status("elderly_001") == {"draft": 2, "archived": 1}


# ---------------------------------------------------------------------------
# 编排表（M5 预留字段必须能被正确写入）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compilation_prompt_package_and_video_url_none(_db):
    async with _db() as session:
        repo = CompilationRepo(session)
        comp = await repo.create("elderly_001", title="王阿姨的纺织厂岁月", story_ids=[1, 2])
        await session.commit()
        assert comp.status == "queued"
        assert comp.video_url is None                    # 契约6：不生成画面

        pkg = {"title": "王阿姨的纺织厂岁月", "perspective": "first_person", "scenes": []}
        assert await repo.set_prompt_package(comp.id, pkg, model="fake") is True
        await session.commit()

        reloaded = await repo.get(comp.id, "elderly_001")
        assert reloaded.status == "prompt_ready"
        assert reloaded.prompt_package["title"] == "王阿姨的纺织厂岁月"
        assert reloaded.video_url is None

    # 归属校验：换个老人取不到
    async with _db() as session:
        assert await CompilationRepo(session).get(1, "elderly_999") is None


# ---------------------------------------------------------------------------
# /chat 后台派发链路（提取器 → 服务 → 仓储 → 落库）
# ---------------------------------------------------------------------------

class _FakeStoryExtractor:
    def __init__(self, result):
        self._result = result

    async def extract(self, user_message, ai_reply=""):
        return self._result


@pytest.mark.asyncio
async def test_chat_background_task_persists_story(_db, monkeypatch):
    """整条派发链路：后台任务拿到提取结果后，真的写进 life_stories。"""
    from app.api.v1 import chat as chat_module

    monkeypatch.setattr(chat_module, "get_session_factory", lambda: _db)

    await chat_module._extract_and_save_story(
        _FakeStoryExtractor(_extraction()), "elderly_001", "那年我进厂了。", "辛苦了。"
    )

    async with _db() as session:
        rows = await StoryRepo(session).list_by_status("elderly_001", "pending_confirm")
        assert len(rows) == 1
        assert rows[0].title == "纺织厂的第一天"


@pytest.mark.asyncio
async def test_chat_background_task_silent_when_no_story(_db, monkeypatch):
    """无 Key / 非故事：后台任务静默返回，不抛错、不落库。"""
    from app.api.v1 import chat as chat_module

    monkeypatch.setattr(chat_module, "get_session_factory", lambda: _db)

    await chat_module._extract_and_save_story(
        _FakeStoryExtractor(None), "elderly_001", "今天天气不错。", "适合散步。"
    )

    async with _db() as session:
        assert await StoryRepo(session).list_by_status("elderly_001", "draft") == []
        assert await StoryRepo(session).list_by_status("elderly_001", "pending_confirm") == []
