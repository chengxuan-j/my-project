"""M2 老人端确认接口测试。

重点验证契约1（确认权只在老人端）与契约2（创伤归档后仍是 private）。
用 httpx ASGITransport 直连 ASGI app，跑真实路由 + 真实 JWT 鉴权；
每个用例在同一事件循环内重建内存库，避免 async engine 跨 loop 复用。
"""
import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "test-secret"

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.security import create_access_token  # noqa: E402
from app.db.base import dispose_engine, get_session_factory, init_async_db  # noqa: E402
from app.main import app  # noqa: E402
from app.repositories.account_repo import AccountRepo  # noqa: E402
from app.repositories.story_repo import StoryRepo  # noqa: E402


async def _bootstrap():
    """在当前事件循环里重建一个干净的内存库（含回忆录四张表）。"""
    await dispose_engine()
    await init_async_db()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_elderly(username: str = "m2_elder", name: str = "王阿姨") -> tuple[str, str]:
    """建一个老人账号，返回 (user_id, token)。"""
    async with get_session_factory()() as session:
        acc = await AccountRepo(session).create_elderly(username, "pwd123", name=name)
        await session.commit()
    return acc.user_id, create_access_token(acc.user_id, role="elderly")


async def _seed_family(username: str = "m2_family") -> tuple[str, str]:
    async with get_session_factory()() as session:
        acc = await AccountRepo(session).create_family(
            username, "pwd123", email=f"{username}@example.com"
        )
        await session.commit()
    return acc.user_id, create_access_token(acc.user_id, role="family")


async def _seed_story(elderly_user_id: str, **kw) -> int:
    async with get_session_factory()() as session:
        defaults = dict(
            title="纺织厂的第一天",
            summary="十八岁进纺织厂。",
            time_value="1973 年",
            place="纺织厂",
            people=["老王"],
            status="pending_confirm",
        )
        defaults.update(kw)
        story = await StoryRepo(session).create(elderly_user_id, **defaults)
        await session.commit()
        return story.id


# ---------------------------------------------------------------------------
# 契约1：只有老人能确认
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pending_requires_auth():
    await _bootstrap()
    async with _client() as ac:
        assert (await ac.get("/api/v1/stories/pending")).status_code == 401


@pytest.mark.asyncio
async def test_family_cannot_list_or_confirm():
    """家属账号必须 403——不能看 pending，更不能代点确认。"""
    await _bootstrap()
    elderly_id, _ = await _seed_elderly()
    story_id = await _seed_story(elderly_id)
    _, family_token = await _seed_family()

    async with _client() as ac:
        r1 = await ac.get("/api/v1/stories/pending", headers=_auth(family_token))
        assert r1.status_code == 403

        r2 = await ac.post(f"/api/v1/stories/{story_id}/confirm", headers=_auth(family_token))
        assert r2.status_code == 403

        r3 = await ac.post(f"/api/v1/stories/{story_id}/discard", headers=_auth(family_token))
        assert r3.status_code == 403


@pytest.mark.asyncio
async def test_cross_elderly_returns_404():
    """别人的条目：越权与不存在同样返回 404，不泄露存在性。"""
    await _bootstrap()
    owner_id, _ = await _seed_elderly("m2_owner")
    story_id = await _seed_story(owner_id)
    _, other_token = await _seed_elderly("m2_other")

    async with _client() as ac:
        r = await ac.post(f"/api/v1/stories/{story_id}/confirm", headers=_auth(other_token))
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# 卡片列表
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pending_lists_only_pending_and_builds_speech():
    await _bootstrap()
    elderly_id, token = await _seed_elderly()
    await _seed_story(elderly_id, title="待确认的")
    await _seed_story(elderly_id, title="太碎的", status="draft")
    await _seed_story(elderly_id, title="已归档的", status="archived")

    async with _client() as ac:
        r = await ac.get("/api/v1/stories/pending", headers=_auth(token))
        assert r.status_code == 200
        items = r.json()
        assert [i["title"] for i in items] == ["待确认的"]
        # 留档播报语应含时间/地点/人物，供 TTS 念
        assert "1973 年" in items[0]["speak_text"]
        assert "老王" in items[0]["speak_text"]
        assert items[0]["speak_text"].endswith("对吗？")


# ---------------------------------------------------------------------------
# 确认 / 弃用 / 恢复
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_confirm_archives():
    await _bootstrap()
    elderly_id, token = await _seed_elderly()
    story_id = await _seed_story(elderly_id)

    async with _client() as ac:
        r = await ac.post(
            f"/api/v1/stories/{story_id}/confirm", headers=_auth(token), json={"via": "voice"}
        )
        assert r.status_code == 200
        assert r.json()["status"] == "archived"

    async with get_session_factory()() as session:
        story = await StoryRepo(session).get(story_id)
        assert story.status == "archived"


@pytest.mark.asyncio
async def test_confirm_trauma_stays_private_after_archive():
    """契约2：归档不会把创伤故事的可见性放开。"""
    await _bootstrap()
    elderly_id, token = await _seed_elderly()
    story_id = await _seed_story(
        elderly_id, title="老伴走了", emotion_tone="创伤",
        visibility="private", visibility_locked=True,
    )

    async with _client() as ac:
        r = await ac.post(f"/api/v1/stories/{story_id}/confirm", headers=_auth(token))
        assert r.status_code == 200

    async with get_session_factory()() as session:
        story = await StoryRepo(session).get(story_id)
        assert story.status == "archived"
        assert story.visibility == "private"      # 仍然私有
        assert story.visibility_locked is True
        # 家属可见集合里不应出现它
        visible = await StoryRepo(session).list_visible_for_family(elderly_id)
        assert story_id not in {s.id for s in visible}


@pytest.mark.asyncio
async def test_confirm_twice_conflicts():
    await _bootstrap()
    elderly_id, token = await _seed_elderly()
    story_id = await _seed_story(elderly_id)

    async with _client() as ac:
        assert (await ac.post(f"/api/v1/stories/{story_id}/confirm", headers=_auth(token))).status_code == 200
        assert (await ac.post(f"/api/v1/stories/{story_id}/confirm", headers=_auth(token))).status_code == 409


@pytest.mark.asyncio
async def test_discard_then_restore():
    await _bootstrap()
    elderly_id, token = await _seed_elderly()
    story_id = await _seed_story(elderly_id)

    async with _client() as ac:
        r1 = await ac.post(f"/api/v1/stories/{story_id}/discard", headers=_auth(token))
        assert r1.status_code == 200 and r1.json()["status"] == "discarded"

        # 弃用后不在待确认列表里
        pending = (await ac.get("/api/v1/stories/pending", headers=_auth(token))).json()
        assert story_id not in {i["id"] for i in pending}

        r2 = await ac.post(f"/api/v1/stories/{story_id}/restore", headers=_auth(token))
        assert r2.status_code == 200 and r2.json()["status"] == "pending_confirm"

        pending2 = (await ac.get("/api/v1/stories/pending", headers=_auth(token))).json()
        assert story_id in {i["id"] for i in pending2}


@pytest.mark.asyncio
async def test_restore_rejects_non_discarded():
    await _bootstrap()
    elderly_id, token = await _seed_elderly()
    story_id = await _seed_story(elderly_id)  # pending_confirm

    async with _client() as ac:
        r = await ac.post(f"/api/v1/stories/{story_id}/restore", headers=_auth(token))
        assert r.status_code == 409
