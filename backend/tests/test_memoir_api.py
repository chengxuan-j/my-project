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
from app.repositories.story_repo import (
    CompilationRepo,
    ElicitationRepo,
    StoryMediaRepo,
    StoryRepo,
)  # noqa: E402


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


# ---------------------------------------------------------------------------
# 短片界面：手动保存（文字/语音转写）与永久删除
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("input_type", ["text", "voice"])
async def test_manual_story_saves_exact_content(input_type):
    await _bootstrap()
    elderly_id, token = await _seed_elderly()
    content = "小时候过年，母亲才蒸一锅白面馒头。"

    async with _client() as ac:
        r = await ac.post(
            "/api/v1/memoir/stories",
            headers=_auth(token),
            json={"title": "", "content": content, "input_type": input_type},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["summary"] == content
        assert body["status"] == "archived"
        assert body["title"]

        timeline = await ac.get("/api/v1/memoir/timeline?status=archived", headers=_auth(token))
        assert body["id"] in {
            s["id"]
            for group in timeline.json()["era_axis"] for s in group["stories"]
        } | {s["id"] for s in timeline.json()["absolute_axis"]} | {
            s["id"] for s in timeline.json()["unlocated"]
        }

    async with get_session_factory()() as session:
        story = await StoryRepo(session).get(body["id"])
        assert story.elderly_user_id == elderly_id
        assert story.visibility == "private"
        turn = story.raw_dialogue[0]
        assert turn["role"] == "user"
        assert turn["content"] == content
        assert turn["input_type"] == input_type
        assert turn["origin"] == "short_film_draft"


@pytest.mark.asyncio
async def test_manual_story_list_only_returns_own_drafts():
    """草稿箱只列手动保存的故事，聊天自动归档的回忆不进列表（避免误删）。"""
    await _bootstrap()
    elderly_id, token = await _seed_elderly()
    chat_story = await _seed_story(elderly_id, status="archived")

    async with _client() as ac:
        saved = await ac.post(
            "/api/v1/memoir/stories", headers=_auth(token),
            json={"content": "那年冬天特别冷。", "input_type": "text"},
        )
        listed = await ac.get("/api/v1/memoir/manual-stories", headers=_auth(token))
        assert listed.status_code == 200
        ids = [s["id"] for s in listed.json()]
        assert saved.json()["id"] in ids
        assert chat_story not in ids

        await ac.delete(f"/api/v1/memoir/stories/{saved.json()['id']}", headers=_auth(token))
        after = await ac.get("/api/v1/memoir/manual-stories", headers=_auth(token))
        assert saved.json()["id"] not in [s["id"] for s in after.json()]


@pytest.mark.asyncio
async def test_story_draft_next_returns_question(monkeypatch):
    """追问接口不依赖真实模型：这里替换成固定问句，验证路由与鉴权。"""
    await _bootstrap()
    _, token = await _seed_elderly()
    _, family_token = await _seed_family()

    from app.memoir import story_chat

    async def fake_next(turns, client=None):
        assert turns == [
            {"role": "user", "content": "我十七岁那年去修水库。"},
        ]
        return {"question": "听着就冷。后来呢？", "focus": "progress",
                "done": False, "source": "llm"}

    monkeypatch.setattr(story_chat, "next_reply", fake_next)

    async with _client() as ac:
        r = await ac.post(
            "/api/v1/memoir/story-draft/next",
            headers=_auth(token),
            json={"turns": [{"role": "user", "content": "我十七岁那年去修水库。"}]},
        )
        assert r.status_code == 200
        assert r.json()["question"] == "听着就冷。后来呢？"
        assert r.json()["done"] is False

        family = await ac.post(
            "/api/v1/memoir/story-draft/next",
            headers=_auth(family_token),
            json={"turns": [{"role": "user", "content": "家属不能替老人讲故事。"}]},
        )
        assert family.status_code == 403


@pytest.mark.asyncio
async def test_manual_story_keeps_dialogue_turns():
    """对话式保存：老人原话与小忆的追问按顺序留底，原文仍是老人说的那句。"""
    await _bootstrap()
    _, token = await _seed_elderly()
    turns = [
        {"role": "user", "content": "我十七岁那年去修水库。"},
        {"role": "assistant", "content": "那天您是怎么去的？"},
        {"role": "user", "content": "走着去的，天没亮就出发。"},
    ]

    async with _client() as ac:
        r = await ac.post(
            "/api/v1/memoir/stories", headers=_auth(token),
            json={
                "content": "我十七岁那年去修水库。\n走着去的，天没亮就出发。",
                "input_type": "voice",
                "turns": turns,
            },
        )
        assert r.status_code == 200
        story_id = r.json()["id"]

    async with get_session_factory()() as session:
        story = await StoryRepo(session).get(story_id)
        assert [t["role"] for t in story.raw_dialogue] == ["user", "assistant", "user"]
        assert story.raw_dialogue[0]["origin"] == "short_film_draft"
        assert story.raw_dialogue[1]["content"] == "那天您是怎么去的？"
        assert story.summary.endswith("天没亮就出发。")


@pytest.mark.asyncio
async def test_long_demo_story_can_be_saved():
    """演示剧本 60+ 句也要能存：turns 上限不能被 40 卡住。"""
    await _bootstrap()
    _, token = await _seed_elderly()
    turns = []
    for i in range(34):
        turns.append({"role": "user", "content": f"第 {i} 段往事，那天很冷。"})
        turns.append({"role": "assistant", "content": f"后来呢？{i}"})
    content = "\n".join(t["content"] for t in turns if t["role"] == "user")

    async with _client() as ac:
        r = await ac.post(
            "/api/v1/memoir/stories", headers=_auth(token),
            json={"content": content, "input_type": "text", "turns": turns},
        )
        assert r.status_code == 200
        story_id = r.json()["id"]

    async with get_session_factory()() as session:
        story = await StoryRepo(session).get(story_id)
        assert len(story.raw_dialogue) == 68


@pytest.mark.asyncio
async def test_manual_story_rejects_blank_and_family():
    await _bootstrap()
    _, elderly_token = await _seed_elderly()
    _, family_token = await _seed_family()
    async with _client() as ac:
        blank = await ac.post(
            "/api/v1/memoir/stories", headers=_auth(elderly_token),
            json={"content": "  ", "input_type": "text"},
        )
        assert blank.status_code == 422
        family = await ac.post(
            "/api/v1/memoir/stories", headers=_auth(family_token),
            json={"content": "家属不能代存", "input_type": "text"},
        )
        assert family.status_code == 403


@pytest.mark.asyncio
async def test_delete_story_checks_ownership():
    await _bootstrap()
    owner_id, _ = await _seed_elderly("m2_delete_owner")
    story_id = await _seed_story(owner_id, status="archived")
    _, other_token = await _seed_elderly("m2_delete_other")
    _, family_token = await _seed_family("m2_delete_family")

    async with _client() as ac:
        other = await ac.delete(f"/api/v1/memoir/stories/{story_id}", headers=_auth(other_token))
        family = await ac.delete(f"/api/v1/memoir/stories/{story_id}", headers=_auth(family_token))
        assert other.status_code == 404
        assert family.status_code == 403
    async with get_session_factory()() as session:
        assert await StoryRepo(session).get(story_id) is not None


@pytest.mark.asyncio
async def test_delete_story_removes_dependent_media_queue_and_compilations():
    await _bootstrap()
    elderly_id, token = await _seed_elderly()
    story_id = await _seed_story(elderly_id, status="archived")
    async with get_session_factory()() as session:
        media = await StoryMediaRepo(session).add(story_id, url="")
        await ElicitationRepo(session).add(
            elderly_id, story_id, question="当时在哪里？", gap_type="missing_detail",
        )
        comp = await CompilationRepo(session).create(
            elderly_id, story_ids=[story_id], created_by=elderly_id,
        )
        media_id, comp_id = media.id, comp.id
        await session.commit()

    async with _client() as ac:
        r = await ac.delete(f"/api/v1/memoir/stories/{story_id}", headers=_auth(token))
        assert r.status_code == 200
        assert r.json() == {"deleted": True, "id": story_id, "deleted_compilations": 1}

    async with get_session_factory()() as session:
        assert await StoryRepo(session).get(story_id) is None
        assert await StoryMediaRepo(session).get(media_id) is None
        assert await ElicitationRepo(session).for_story(story_id) == []
        assert await CompilationRepo(session).get(comp_id) is None
