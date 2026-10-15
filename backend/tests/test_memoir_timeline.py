"""M3 回忆录时间轴测试。

分三层：
1. 纯函数层：`parse_year` / `infer_time_from_profile`（不碰 DB）
2. 编排层：`build_timeline` 的三组切分与排序（只读 ORM 对象）
3. 接口层：老人端 timeline 的门禁与家属端 private 过滤（真实 ASGI + JWT）

契约重点：
- 契约5：时间轴是**只读**的，推断不回写 ORM，原文 `time_value` 永不变；
- 契约2：家属端响应里不得出现 private 故事。
"""
import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "test-secret"

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.security import create_access_token  # noqa: E402
from app.db.base import dispose_engine, get_session_factory, init_async_db  # noqa: E402
from app.main import app  # noqa: E402
from app.memoir.timeline import (  # noqa: E402
    INFERRED_CONFIDENCE_CAP,
    build_timeline,
    infer_time_from_profile,
    parse_year,
)
from app.repositories.account_repo import AccountRepo  # noqa: E402
from app.repositories.profile_repo import FamilyRepo  # noqa: E402
from app.repositories.story_repo import StoryRepo  # noqa: E402


class _Created:
    """`created_at` 的最小替身：只要可 isoformat + 可比较。"""

    def __init__(self, dt: str):
        self._dt = dt

    def isoformat(self) -> str:
        return self._dt

    def __lt__(self, other):
        return self._dt < other._dt


class FakeStory:
    """只带 build_timeline 需要的字段，避免为纯函数测试起数据库。"""

    def __init__(self, **kw):
        self.id = kw.get("id", 0)
        self.title = kw.get("title", "")
        self.summary = kw.get("summary", "")
        self.time_type = kw.get("time_type", "relative")
        self.time_value = kw.get("time_value", "")
        self.time_confidence = kw.get("time_confidence", 0.0)
        self.time_inferred = kw.get("time_inferred", False)
        self.era_tags = kw.get("era_tags", [])
        self.place = kw.get("place", "")
        self.people = kw.get("people", [])
        self.emotion_tone = kw.get("emotion_tone", "平淡")
        self.completeness = kw.get("completeness", 0.6)
        self.status = kw.get("status", "archived")
        self.created_at = _Created(kw.get("created_key", "2026-01-01T00:00:00"))


# ---------------------------------------------------------------------------
# 1. parse_year
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("1973年", 1973),
    ("1973 年", 1973),
    ("1973年春天", 1973),
    ("一九七三年", 1973),
    ("二〇〇〇年", 2000),
    ("七十年代", 1970),
    ("八十年代初", 1980),
    ("上世纪80年代", 1980),
    ("上世纪七十年代", 1970),
    ("两千年", 2000),
    ("小时候", None),
    ("", None),
    ("最近", None),
    ("1245", None),          # 不在 19xx/20xx 区间
])
def test_parse_year(text, expected):
    assert parse_year(text) == expected


# ---------------------------------------------------------------------------
# 2. P4 降级：画像保守推断
# ---------------------------------------------------------------------------

def test_infer_time_hits_shared_anchor():
    story = FakeStory(title="车间里的学徒", summary="我进纺织厂当学徒，师傅姓王。")
    hit = infer_time_from_profile(story, ["1973年进纺织厂", "1996年下岗"])
    assert hit is not None
    year, confidence, evidence = hit
    assert year == 1973
    assert evidence.startswith("1973年进纺织厂")
    assert confidence <= INFERRED_CONFIDENCE_CAP


def test_infer_time_requires_year_in_entry():
    """入口没有年份就无从推断——下门必须关死。"""
    story = FakeStory(summary="我进纺织厂当学徒。")
    assert infer_time_from_profile(story, ["进纺织厂当学徒"]) is None


def test_infer_time_rejects_weak_overlap():
    """只共享一个泛词不足以推断（保守：宁可不给时间）。"""
    story = FakeStory(summary="那天厂子门口人很多。")
    # 条目锚词是「厂子改制」，与故事仅共享「厂子」一个词对 → 不命中
    assert infer_time_from_profile(story, ["1993年厂子改制"]) is None


def test_infer_time_picks_earliest_when_tie():
    story = FakeStory(summary="我在纺织厂上班，后来下岗了。")
    hit = infer_time_from_profile(story, ["1996年下岗", "1973年进纺织厂"])
    assert hit is not None and hit[0] == 1973


# ---------------------------------------------------------------------------
# 3. build_timeline：三组互斥且完备
# ---------------------------------------------------------------------------

def test_three_groups_are_partitioned():
    stories = [
        FakeStory(id=1, era_tags=["知青年代"]),
        FakeStory(id=2, era_tags=["上山下乡"]),       # 同义词 → 归一
        FakeStory(id=3, time_value="1988年"),        # 无时代标签，有绝对年
        FakeStory(id=4),                             # 什么都没有
    ]
    tl = build_timeline(stories)
    assert [g["era"] for g in tl["era_axis"]] == ["知青年代"]
    assert tl["era_axis"][0]["count"] == 2
    assert [s.id for s in tl["absolute_axis"]] == [3]
    assert [s.id for s in tl["unlocated"]] == [4]
    # 完备性：总数 = 各组之和（每条恰好落一组）
    assert tl["stats"]["total"] == 4
    assert tl["stats"]["total"] == (
        tl["stats"]["in_era"] + tl["stats"]["in_absolute"] + tl["stats"]["unlocated"]
    )


def test_era_axis_sorted_by_start_year():
    stories = [
        FakeStory(id=1, era_tags=["下岗改制"]),        # 1993
        FakeStory(id=2, era_tags=["知青年代"]),        # 1968
        FakeStory(id=3, era_tags=["改革开放初期"]),    # 1978
    ]
    tl = build_timeline(stories)
    assert [g["era"] for g in tl["era_axis"]] == ["知青年代", "改革开放初期", "下岗改制"]
    assert tl["era_axis"][0]["color"].startswith("#")


def test_multi_era_story_appears_only_once():
    """双时代标签的故事只进最早那一段，避免时代带上出现两次、计数虚高。"""
    stories = [
        FakeStory(id=1, era_tags=["文革时期", "知青年代"]),
        FakeStory(id=2, era_tags=["知青年代"]),
    ]
    tl = build_timeline(stories)
    assert [g["era"] for g in tl["era_axis"]] == ["文革时期", "知青年代"]
    placed = [s.id for g in tl["era_axis"] for s in g["stories"]]
    assert sorted(placed) == [1, 2]          # 没有重复
    assert tl["stats"]["total"] == 2
    # 信息不丢：卡片上仍带完整 era_tags
    card = tl["era_axis"][0]["stories"][0]
    assert card.era == "文革时期"
    assert set(card.era_tags) == {"文革时期", "知青年代"}


def test_absolute_axis_sorted_by_year():
    stories = [
        FakeStory(id=1, time_value="1996年"),
        FakeStory(id=2, time_value="1973年"),
        FakeStory(id=3, time_value="1988年"),
    ]
    tl = build_timeline(stories)
    assert [s.display_time for s in tl["absolute_axis"]] == ["1973年", "1988年", "1996年"]
    assert tl["axis_span"] == {"min_year": 1973, "max_year": 1996}


def test_era_story_keeps_own_year_in_display_time():
    tl = build_timeline([FakeStory(id=1, era_tags=["知青年代"], time_value="1969年")])
    assert tl["era_axis"][0]["stories"][0].display_time == "1969年"


def test_era_story_without_year_falls_back_to_era_span():
    tl = build_timeline([FakeStory(id=1, era_tags=["知青年代"])])
    assert tl["era_axis"][0]["stories"][0].display_time == "约1968—1978年"


def test_profile_inference_lands_in_absolute_with_cap():
    """画像推断出的年份进绝对时间轴，且一定是「约」+ 低置信度。"""
    stories = [FakeStory(id=9, summary="我进纺织厂当学徒。")]
    tl = build_timeline(stories, profile_entries=["1973年进纺织厂"])
    assert tl["stats"]["inferred"] == 1
    card = tl["absolute_axis"][0]
    assert card.display_time == "约1973年"
    assert card.time_inferred is True
    assert card.time_confidence <= INFERRED_CONFIDENCE_CAP
    assert card.inferred_from.startswith("1973年进纺织厂")
    # 由年份反推时代，但仍是推断
    assert card.era == "知青年代"


def test_contract5_timeline_is_read_only():
    """契约5：编排只读——ORM 对象上的原文与标记不得被改写。"""
    story = FakeStory(id=5, summary="我进纺织厂当学徒。", time_value="", time_confidence=0.0)
    build_timeline([story], profile_entries=["1973年进纺织厂"])
    assert story.time_value == ""          # 原文未被改写
    assert story.time_inferred is False    # ORM 上的标记未被污染
    assert story.time_confidence == 0.0


# ---------------------------------------------------------------------------
# 4. 接口层
# ---------------------------------------------------------------------------

async def _bootstrap():
    await dispose_engine()
    await init_async_db()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_elderly(username: str, name: str = "王阿姨", experiences=None) -> tuple[str, str]:
    async with get_session_factory()() as session:
        acc = await AccountRepo(session).create_elderly(username, "pwd123", name=name)
        if experiences:
            from sqlalchemy import select
            from app.db.models import ElderlyProfile
            prof = (await session.execute(
                select(ElderlyProfile).where(ElderlyProfile.user_id == acc.user_id)
            )).scalar_one()
            prof.life_experience = list(experiences)
        await session.commit()
    return acc.user_id, create_access_token(acc.user_id, role="elderly")


async def _seed_family(username: str, bind_to: str | None = None) -> tuple[str, str]:
    async with get_session_factory()() as session:
        acc = await AccountRepo(session).create_family(
            username, "pwd123", email=f"{username}@example.com"
        )
        if bind_to:
            await FamilyRepo(session).bind(acc.user_id, bind_to)
        await session.commit()
    return acc.user_id, create_access_token(acc.user_id, role="family")


async def _seed_story(elderly_user_id: str, **kw) -> int:
    async with get_session_factory()() as session:
        defaults = dict(status="archived", visibility="family")
        defaults.update(kw)
        story = await StoryRepo(session).create(elderly_user_id, **defaults)
        await session.commit()
        return story.id


@pytest.mark.asyncio
async def test_timeline_requires_elderly():
    await _bootstrap()
    elderly_id, _ = await _seed_elderly("m3_elder_a")
    _, family_token = await _seed_family("m3_family_a", bind_to=elderly_id)

    async with _client() as ac:
        assert (await ac.get("/api/v1/memoir/timeline")).status_code == 401
        assert (await ac.get("/api/v1/memoir/timeline", headers=_auth(family_token))).status_code == 403


@pytest.mark.asyncio
async def test_timeline_renders_two_eras_plus_unlocated():
    """M3 验收：至少 2 个时代段 + 未定位区。"""
    await _bootstrap()
    elderly_id, token = await _seed_elderly("m3_elder_b")
    await _seed_story(elderly_id, title="下乡", era_tags=["知青年代"], time_value="1969年")
    await _seed_story(elderly_id, title="下岗", era_tags=["下岗改制"], time_value="1996年")
    await _seed_story(elderly_id, title="说不清", era_tags=[], time_value="")

    async with _client() as ac:
        r = await ac.get("/api/v1/memoir/timeline", headers=_auth(token))
        assert r.status_code == 200
        body = r.json()
        assert [g["era"] for g in body["era_axis"]] == ["知青年代", "下岗改制"]
        assert len(body["era_axis"]) >= 2
        assert [s["title"] for s in body["unlocated"]] == ["说不清"]
        assert body["stats"]["total"] == 3
        assert body["user_id"] == elderly_id


@pytest.mark.asyncio
async def test_timeline_default_hides_unconfirmed():
    await _bootstrap()
    elderly_id, token = await _seed_elderly("m3_elder_c")
    await _seed_story(elderly_id, title="已留档", status="archived")
    await _seed_story(elderly_id, title="草稿", status="draft")
    await _seed_story(elderly_id, title="待确认", status="pending_confirm")

    async with _client() as ac:
        default = (await ac.get("/api/v1/memoir/timeline", headers=_auth(token))).json()
        assert default["stats"]["total"] == 1

        allst = (await ac.get(
            "/api/v1/memoir/timeline?status=all", headers=_auth(token)
        )).json()
        assert allst["stats"]["total"] == 3

        bad = await ac.get("/api/v1/memoir/timeline?status=nope", headers=_auth(token))
        assert bad.status_code == 422


@pytest.mark.asyncio
async def test_timeline_uses_profile_to_infer_year():
    await _bootstrap()
    elderly_id, token = await _seed_elderly(
        "m3_elder_d", experiences=["1973年进纺织厂", "1996年下岗"]
    )
    await _seed_story(elderly_id, title="车间", summary="我进纺织厂当学徒。", time_value="")

    async with _client() as ac:
        body = (await ac.get("/api/v1/memoir/timeline", headers=_auth(token))).json()
        assert body["stats"]["inferred"] == 1
        card = body["absolute_axis"][0]
        assert card["display_time"] == "约1973年"
        assert card["time_inferred"] is True
        assert card["time_confidence"] <= INFERRED_CONFIDENCE_CAP


# ---------------------------------------------------------------------------
# 5. 家属端：契约2 过滤 + 只读
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_family_memoir_excludes_private():
    await _bootstrap()
    elderly_id, _ = await _seed_elderly("m3_elder_e")
    _, family_token = await _seed_family("m3_family_e", bind_to=elderly_id)

    await _seed_story(elderly_id, title="能看的", visibility="family", status="archived")
    await _seed_story(elderly_id, title="创伤", visibility="private",
                      visibility_locked=True, status="archived")
    await _seed_story(elderly_id, title="没确认", visibility="family", status="pending_confirm")

    async with _client() as ac:
        body = (await ac.get(
            f"/api/v1/family/elderly/{elderly_id}/memoir", headers=_auth(family_token)
        )).json()
        titles = {s["title"] for g in body["era_axis"] for s in g["stories"]}
        titles |= {s["title"] for s in body["absolute_axis"]}
        titles |= {s["title"] for s in body["unlocated"]}
        assert titles == {"能看的"}

        # 家属端不生成给老人念的确认语（省一层无意义话术）
        assert all(
            s["speak_text"] == ""
            for s in body["unlocated"]
        )


@pytest.mark.asyncio
async def test_family_memoir_requires_binding():
    await _bootstrap()
    await _seed_elderly("m3_elder_f")
    other_id, _ = await _seed_elderly("m3_elder_g")
    _, family_token = await _seed_family("m3_family_f")  # 未绑定任何人

    async with _client() as ac:
        r = await ac.get(
            f"/api/v1/family/elderly/{other_id}/memoir", headers=_auth(family_token)
        )
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_family_memoir_family_cannot_confirm():
    """契约1：家属端没有任何写路径。"""
    await _bootstrap()
    elderly_id, _ = await _seed_elderly("m3_elder_h")
    story_id = await _seed_story(elderly_id, status="pending_confirm")
    _, family_token = await _seed_family("m3_family_h", bind_to=elderly_id)

    async with _client() as ac:
        for action in ("confirm", "discard", "restore"):
            r = await ac.post(
                f"/api/v1/family/elderly/{elderly_id}/memoir/{story_id}/{action}",
                headers=_auth(family_token),
            )
            assert r.status_code == 404
