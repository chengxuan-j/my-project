"""M6 家属端回忆录测试：照片上传/读取/删除 + 家属时间轴与短片列表 + 日报回忆文案。

重点契约：
- **契约1**：家属不能替老人确认留档、不能创建/删除短片；照片是唯一能写的东西；
- **契约2**：看得到的前提是「已绑定 + 故事当下 archived 且 visibility ∈ (family, public)」。
  老人把故事改成 private 之后，照片**立即**对家属不可见（不是前端隐藏）；
- **契约5**：上传照片不改动 `raw_dialogue` / `summary`，也不改可见性；
- 照片走**鉴权接口**而不是静态目录，且以文件头判类型（客户端说是什么不算数）。

不依赖 LLM Key。
"""
import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "test-secret"

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.security import create_access_token  # noqa: E402
from app.db.base import dispose_engine, get_session_factory, init_async_db  # noqa: E402
from app.main import app  # noqa: E402
from app.memoir import media_service as MS  # noqa: E402
from app.repositories.account_repo import AccountRepo  # noqa: E402
from app.repositories.profile_repo import FamilyRepo  # noqa: E402
from app.repositories.story_repo import StoryMediaRepo, StoryRepo  # noqa: E402

# ---------------------------------------------------------------------------
# 测试替身与工具
# ---------------------------------------------------------------------------

PNG_HEAD = b"\x89PNG\r\n\x1a\n"
JPG_HEAD = b"\xff\xd8\xff"


def _png(payload: bytes = b"x" * 32) -> bytes:
    return PNG_HEAD + payload


def _jpg(payload: bytes = b"y" * 32) -> bytes:
    return JPG_HEAD + payload


@pytest.fixture(autouse=True)
def _media_tmpdir(tmp_path, monkeypatch):
    """照片落到临时目录，别把真库旁边的 storage/memoir_media 搞脏。

    ⚠️ 这里**刻意不**用 `get_settings.cache_clear()`。整套测试有一个潜伏前提：
    `get_settings()` 是 lru_cache 的，而各测试文件在模块级各自改写
    `os.environ["DATABASE_URL"]`（最后一个是 `test_rag.py`，指向**磁盘**上的 rag.db）。
    全量跑时设置对象在收集早期就被缓存成 `:memory:`，于是所有用例共享内存库；
    一旦中途 clear 缓存，后续用例会重新读到 rag.db → 变成**持久化文件库**，
    数据跨用例泄漏（表现为 `test_memoir_repo` 里凭空多出几条 story）。

    所以这里只把 `media_service` 命名空间里的 `get_settings` 换成一个固定 stub，
    作用域严格限制在本文件，不碰全局缓存。
    """
    from app.config import Settings

    stub = Settings(
        memoir_media_dir=str(tmp_path / "media"),
        memoir_media_max_mb=1,
    )
    monkeypatch.setattr(MS, "get_settings", lambda: stub)
    yield


async def _bootstrap():
    await dispose_engine()
    await init_async_db()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_elderly(username: str) -> tuple[str, str]:
    async with get_session_factory()() as session:
        acc = await AccountRepo(session).create_elderly(username, "pwd123", name="王阿姨")
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


async def _seed_story(user_id: str, **kw) -> int:
    async with get_session_factory()() as session:
        defaults = dict(
            status="archived", visibility="family", title="下乡",
            summary="十六岁下乡", era_tags=["知青年代"],
            raw_dialogue=[{"role": "user", "content": "我十六岁那年就下乡了"}],
        )
        defaults.update(kw)
        story = await StoryRepo(session).create(user_id, **defaults)
        await session.commit()
        return story.id


async def _upload(ac, url, token, data=None, filename="a.png", ctype="image/png", caption=""):
    return await ac.post(
        url,
        headers=_auth(token),
        files={"file": (filename, data if data is not None else _png(), ctype)},
        data={"caption": caption},
    )


# ---------------------------------------------------------------------------
# 1. 落盘服务（纯逻辑，不碰 DB）
# ---------------------------------------------------------------------------

def test_validate_accepts_real_headers():
    assert MS.validate_image(_png(), "image/png") == ".png"
    assert MS.validate_image(_jpg(), "image/jpeg") == ".jpg"
    assert MS.validate_image(b"GIF89a" + b"z" * 20, "image/gif") == ".gif"
    assert MS.validate_image(b"RIFF" + b"\x00" * 4 + b"WEBP" + b"z" * 8, "") == ".webp"


def test_validate_rejects_empty_and_oversize():
    with pytest.raises(MS.MediaError):
        MS.validate_image(b"", "image/png")
    with pytest.raises(MS.MediaError) as e:
        MS.validate_image(_png(b"x" * (MS.max_bytes() + 1)), "image/png")
    assert "MB" in str(e.value)


def test_validate_rejects_non_image_despite_declared_type():
    """客户端把 HTML 说成 image/jpeg —— 以文件头为准，拒收。"""
    fake = b"<html><script>alert(1)</script></html>" + b" " * 20
    with pytest.raises(MS.MediaError):
        MS.validate_image(fake, "image/jpeg")


def test_resolve_path_blocks_traversal():
    assert MS.resolve_path("") is None
    assert MS.resolve_path("../../etc/passwd") is None
    assert MS.resolve_path("..\\..\\windows\\system32") is None
    assert MS.resolve_path("/etc/passwd") is None
    assert MS.resolve_path("12/../../escape.png") is None
    # 正常相对路径能解析到根目录之下
    ok = MS.resolve_path("12/abcd.png")
    assert ok is not None and MS.media_root() in ok.parents


def test_save_photo_dedupes_by_content():
    a = MS.save_photo(1, _png(b"same"), ".png")
    b = MS.save_photo(1, _png(b"same"), ".png")
    c = MS.save_photo(1, _png(b"other"), ".png")
    assert a == b                      # 同一张图 → 同一个文件
    assert a != c
    assert len(list((MS.media_root() / "1").iterdir())) == 2


def test_remove_photo_is_idempotent():
    rel = MS.save_photo(2, _png(b"del"), ".png")
    assert MS.remove_photo(rel) is True
    assert MS.remove_photo(rel) is True            # 再删一次仍算成功
    assert MS.remove_photo("../../evil") is False  # 越界拒绝


def test_content_type_for_falls_back():
    assert MS.content_type_for("a/b.png") == "image/png"
    assert MS.content_type_for("a/b.unknown") == "application/octet-stream"


# ---------------------------------------------------------------------------
# 2. 上传：老人端
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_elderly_uploads_photo_to_own_story():
    await _bootstrap()
    elderly_id, token = await _seed_elderly("m6_e1")
    sid = await _seed_story(elderly_id)
    async with _client() as ac:
        r = await _upload(ac, f"/api/v1/memoir/stories/{sid}/media", token, caption="那年夏天")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["type"] == "photo"
        assert body["caption"] == "那年夏天"
        assert body["uploaded_by_role"] == "owner"       # 不回传真实 user_id
        assert body["url"] == f"/api/v1/memoir/media/{body['id']}"
        assert elderly_id not in r.text


@pytest.mark.asyncio
async def test_elderly_cannot_upload_to_others_story():
    await _bootstrap()
    _, token_a = await _seed_elderly("m6_e2a")
    other_id, _ = await _seed_elderly("m6_e2b")
    sid = await _seed_story(other_id)
    async with _client() as ac:
        r = await _upload(ac, f"/api/v1/memoir/stories/{sid}/media", token_a)
        assert r.status_code == 404     # 越权与不存在同码，不泄露存在性


@pytest.mark.asyncio
async def test_upload_rejects_bad_file():
    await _bootstrap()
    elderly_id, token = await _seed_elderly("m6_e3")
    sid = await _seed_story(elderly_id)
    async with _client() as ac:
        r = await _upload(
            ac, f"/api/v1/memoir/stories/{sid}/media", token,
            data=b"<html>not a photo</html>" + b" " * 20, ctype="image/png",
        )
        assert r.status_code == 400
    async with get_session_factory()() as session:
        assert await StoryMediaRepo(session).list_for_story(sid) == []


@pytest.mark.asyncio
async def test_upload_does_not_touch_story_content():
    """契约5/1：挂照片既不改原文，也不改可见性。"""
    await _bootstrap()
    elderly_id, token = await _seed_elderly("m6_e4")
    sid = await _seed_story(elderly_id, visibility="private", visibility_locked=True,
                            raw_dialogue=[{"role": "user", "content": "原话不许动"}])
    async with _client() as ac:
        assert (await _upload(ac, f"/api/v1/memoir/stories/{sid}/media", token)).status_code == 200

    async with get_session_factory()() as session:
        story = await StoryRepo(session).get(sid)
        assert story.raw_dialogue == [{"role": "user", "content": "原话不许动"}]
        assert story.summary == "十六岁下乡"
        assert story.visibility == "private" and story.visibility_locked is True


# ---------------------------------------------------------------------------
# 3. 上传：家属端（三道门）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_family_uploads_to_visible_story():
    await _bootstrap()
    elderly_id, _ = await _seed_elderly("m6_f1")
    sid = await _seed_story(elderly_id)
    _, ftoken = await _seed_family("m6_f1b", bind_to=elderly_id)
    url = f"/api/v1/family/elderly/{elderly_id}/memoir/stories/{sid}/media"
    async with _client() as ac:
        r = await _upload(ac, url, ftoken, caption="妈的老照片")
        assert r.status_code == 200, r.text
        assert r.json()["uploaded_by_role"] == "family"


@pytest.mark.asyncio
async def test_family_upload_requires_binding():
    await _bootstrap()
    elderly_id, _ = await _seed_elderly("m6_f2")
    sid = await _seed_story(elderly_id)
    _, ftoken = await _seed_family("m6_f2b")           # 未绑定
    url = f"/api/v1/family/elderly/{elderly_id}/memoir/stories/{sid}/media"
    async with _client() as ac:
        assert (await _upload(ac, url, ftoken)).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kw",
    [
        {"status": "draft"},
        {"status": "pending_confirm"},
        {"status": "discarded"},
        {"status": "archived", "visibility": "private", "visibility_locked": True},
    ],
)
async def test_family_cannot_upload_to_invisible_story(kw):
    """控制权在老人手里：没留档、或留档了但设成 private，家属连挂照片都挂不上。"""
    await _bootstrap()
    elderly_id, _ = await _seed_elderly("m6_f3")
    sid = await _seed_story(elderly_id, **kw)
    _, ftoken = await _seed_family("m6_f3b", bind_to=elderly_id)
    url = f"/api/v1/family/elderly/{elderly_id}/memoir/stories/{sid}/media"
    async with _client() as ac:
        assert (await _upload(ac, url, ftoken)).status_code == 404


@pytest.mark.asyncio
async def test_family_cannot_use_elderly_upload_route():
    await _bootstrap()
    elderly_id, _ = await _seed_elderly("m6_f4")
    sid = await _seed_story(elderly_id)
    _, ftoken = await _seed_family("m6_f4b", bind_to=elderly_id)
    async with _client() as ac:
        assert (await _upload(ac, f"/api/v1/memoir/stories/{sid}/media", ftoken)).status_code == 403


# ---------------------------------------------------------------------------
# 4. 读取：鉴权而不是静态目录
# ---------------------------------------------------------------------------

async def _media_id_of(sid: int) -> int:
    async with get_session_factory()() as session:
        rows = await StoryMediaRepo(session).list_for_story(sid)
        return rows[-1].id


@pytest.mark.asyncio
async def test_owner_reads_photo():
    await _bootstrap()
    elderly_id, token = await _seed_elderly("m6_r1")
    sid = await _seed_story(elderly_id)
    async with _client() as ac:
        await _upload(ac, f"/api/v1/memoir/stories/{sid}/media", token)
        mid = await _media_id_of(sid)
        r = await ac.get(f"/api/v1/memoir/media/{mid}", headers=_auth(token))
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/png")
        assert r.content.startswith(PNG_HEAD)


@pytest.mark.asyncio
async def test_family_reads_photo_only_while_visible():
    """契约2 的核心一测：老人一改成 private，家属立刻 404（不是前端藏起来）。"""
    await _bootstrap()
    elderly_id, token = await _seed_elderly("m6_r2")
    sid = await _seed_story(elderly_id)
    _, ftoken = await _seed_family("m6_r2b", bind_to=elderly_id)
    async with _client() as ac:
        await _upload(ac, f"/api/v1/memoir/stories/{sid}/media", token)
        mid = await _media_id_of(sid)
        assert (await ac.get(f"/api/v1/memoir/media/{mid}",
                             headers=_auth(ftoken))).status_code == 200

        # 老人收回可见性
        async with get_session_factory()() as session:
            await StoryRepo(session).set_visibility(sid, "private")
            await session.commit()

        assert (await ac.get(f"/api/v1/memoir/media/{mid}",
                             headers=_auth(ftoken))).status_code == 404
        # 老人本人照样能看
        assert (await ac.get(f"/api/v1/memoir/media/{mid}",
                             headers=_auth(token))).status_code == 200


@pytest.mark.asyncio
async def test_photo_read_denied_for_stranger_and_anonymous():
    await _bootstrap()
    elderly_id, token = await _seed_elderly("m6_r3")
    sid = await _seed_story(elderly_id)
    _, stranger_token = await _seed_family("m6_r3b")      # 未绑定
    async with _client() as ac:
        await _upload(ac, f"/api/v1/memoir/stories/{sid}/media", token)
        mid = await _media_id_of(sid)
        assert (await ac.get(f"/api/v1/memoir/media/{mid}",
                             headers=_auth(stranger_token))).status_code == 404
        assert (await ac.get(f"/api/v1/memoir/media/{mid}")).status_code == 401
        assert (await ac.get("/api/v1/memoir/media/999999",
                             headers=_auth(token))).status_code == 404


@pytest.mark.asyncio
async def test_photo_read_404_when_file_missing():
    """库里有记录但盘上没文件（比如换了机器）：404，不是 500。"""
    await _bootstrap()
    elderly_id, token = await _seed_elderly("m6_r4")
    sid = await _seed_story(elderly_id)
    async with get_session_factory()() as session:
        media = await StoryMediaRepo(session).add(
            sid, url="9/not-there.png", uploaded_by=elderly_id
        )
        await session.commit()
        mid = media.id
    async with _client() as ac:
        assert (await ac.get(f"/api/v1/memoir/media/{mid}",
                             headers=_auth(token))).status_code == 404


# ---------------------------------------------------------------------------
# 5. 删除
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_owner_can_delete_family_uploaded_photo():
    await _bootstrap()
    elderly_id, token = await _seed_elderly("m6_d1")
    sid = await _seed_story(elderly_id)
    _, ftoken = await _seed_family("m6_d1b", bind_to=elderly_id)
    async with _client() as ac:
        await _upload(
            ac, f"/api/v1/family/elderly/{elderly_id}/memoir/stories/{sid}/media", ftoken
        )
        mid = await _media_id_of(sid)
        assert (await ac.delete(f"/api/v1/memoir/media/{mid}",
                                headers=_auth(token))).status_code == 200
    async with get_session_factory()() as session:
        assert await StoryMediaRepo(session).get(mid) is None


@pytest.mark.asyncio
async def test_family_deletes_only_own_upload():
    await _bootstrap()
    elderly_id, token = await _seed_elderly("m6_d2")
    sid = await _seed_story(elderly_id)
    _, f1 = await _seed_family("m6_d2b", bind_to=elderly_id)
    _, f2 = await _seed_family("m6_d2c", bind_to=elderly_id)

    async with _client() as ac:
        # 老人自己传的一张
        await _upload(ac, f"/api/v1/memoir/stories/{sid}/media", token)
        own_by_owner = await _media_id_of(sid)
        # 家属 f1 传的一张
        await _upload(
            ac, f"/api/v1/family/elderly/{elderly_id}/memoir/stories/{sid}/media", f1
        )
        by_f1 = await _media_id_of(sid)

        base = f"/api/v1/family/elderly/{elderly_id}/memoir/media"
        # f2 删 f1 传的 → 404
        assert (await ac.delete(f"{base}/{by_f1}", headers=_auth(f2))).status_code == 404
        # f1 删自己传的 → 200
        assert (await ac.delete(f"{base}/{by_f1}", headers=_auth(f1))).status_code == 200
        # 家属删老人传的 → 404（不是自己的）
        assert (await ac.delete(f"{base}/{own_by_owner}",
                                headers=_auth(f1))).status_code == 404

    async with get_session_factory()() as session:
        assert await StoryMediaRepo(session).get(by_f1) is None
        assert await StoryMediaRepo(session).get(own_by_owner) is not None


@pytest.mark.asyncio
async def test_duplicate_content_keeps_file_until_last_row_gone():
    """同内容命名去重：删掉一条记录，不能把另一条还在用的文件干掉。"""
    await _bootstrap()
    elderly_id, token = await _seed_elderly("m6_d3")
    sid = await _seed_story(elderly_id)
    same = _png(b"identical")
    async with _client() as ac:
        await _upload(ac, f"/api/v1/memoir/stories/{sid}/media", token, data=same)
        m1 = await _media_id_of(sid)
        await _upload(ac, f"/api/v1/memoir/stories/{sid}/media", token, data=same)
        m2 = await _media_id_of(sid)
        async with get_session_factory()() as session:
            rows = await StoryMediaRepo(session).list_for_story(sid)
        assert len(rows) == 2 and rows[0].url == rows[1].url   # 共用同一文件

        await ac.delete(f"/api/v1/memoir/media/{m1}", headers=_auth(token))
        rel = rows[0].url
        assert MS.resolve_path(rel).exists()                   # 文件还在

        await ac.delete(f"/api/v1/memoir/media/{m2}", headers=_auth(token))
        assert not MS.resolve_path(rel).exists()               # 没人用了才删盘


# ---------------------------------------------------------------------------
# 6. 时间轴 / 家属列表带上照片与短片
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_timeline_carries_media_for_both_sides():
    await _bootstrap()
    elderly_id, token = await _seed_elderly("m6_t1")
    sid = await _seed_story(elderly_id, summary="十六岁下乡")
    _, ftoken = await _seed_family("m6_t1b", bind_to=elderly_id)
    url = f"/api/v1/family/elderly/{elderly_id}/memoir/stories/{sid}/media"
    async with _client() as ac:
        await _upload(ac, url, ftoken, caption="户口本")

        owner_tl = (await ac.get("/api/v1/memoir/timeline", headers=_auth(token))).json()
        fam_tl = (await ac.get(f"/api/v1/family/elderly/{elderly_id}/memoir",
                               headers=_auth(ftoken))).json()

    def _first_media(tl):
        for g in tl["era_axis"]:
            for s in g["stories"]:
                if s["media"]:
                    return s["media"][0]
        for s in tl["absolute_axis"] + tl["unlocated"]:
            if s["media"]:
                return s["media"][0]
        return None

    owner_media = _first_media(owner_tl)
    fam_media = _first_media(fam_tl)
    assert owner_media and owner_media["caption"] == "户口本"
    assert owner_media["uploaded_by_role"] == "family"
    assert fam_media and fam_media["id"] == owner_media["id"]


@pytest.mark.asyncio
async def test_family_timeline_hides_private_media():
    """private 故事整条都不该出现在家属时间轴里（照片自然也不在）。"""
    await _bootstrap()
    elderly_id, token = await _seed_elderly("m6_t2")
    sid = await _seed_story(elderly_id)
    _, ftoken = await _seed_family("m6_t2b", bind_to=elderly_id)
    async with _client() as ac:
        await _upload(ac, f"/api/v1/memoir/stories/{sid}/media", token)
        async with get_session_factory()() as session:
            await StoryRepo(session).set_visibility(sid, "private")
            await session.commit()
        fam_tl = (await ac.get(f"/api/v1/family/elderly/{elderly_id}/memoir",
                               headers=_auth(ftoken))).json()
    assert fam_tl["stats"]["total"] == 0


@pytest.mark.asyncio
async def test_family_compilation_list_filters_withdrawn_scenes():
    await _bootstrap()
    elderly_id, token = await _seed_elderly("m6_t3")
    keep = await _seed_story(elderly_id, title="留下的")
    drop = await _seed_story(elderly_id, title="要收回的")
    _, ftoken = await _seed_family("m6_t3b", bind_to=elderly_id)
    base = f"/api/v1/family/elderly/{elderly_id}/memoir/compilations"

    async with _client() as ac:
        comp = (await ac.post("/api/v1/memoir/compilations", headers=_auth(token),
                              json={"title": "合片"})).json()
        assert len((await ac.get(base, headers=_auth(ftoken))).json()) == 1

        async with get_session_factory()() as session:
            await StoryRepo(session).set_visibility(drop, "private")
            await session.commit()

        listed = (await ac.get(base, headers=_auth(ftoken))).json()
        scenes = listed[0]["prompt_package"]["scenes"]
        assert {s["story_id"] for s in scenes} == {keep}
        assert listed[0]["prompt_package"]["total_seconds"] == sum(
            s["duration_seconds"] for s in scenes
        )

        # 全部收回 → 整条不再出现（不是返回一个空壳）
        async with get_session_factory()() as session:
            await StoryRepo(session).set_visibility(keep, "private")
            await session.commit()
        assert (await ac.get(base, headers=_auth(ftoken))).json() == []
        assert (await ac.get(f"{base}/{comp['id']}",
                             headers=_auth(ftoken))).status_code == 404


@pytest.mark.asyncio
async def test_family_compilation_list_requires_binding():
    await _bootstrap()
    elderly_id, _ = await _seed_elderly("m6_t4")
    _, ftoken = await _seed_family("m6_t4b")
    async with _client() as ac:
        r = await ac.get(f"/api/v1/family/elderly/{elderly_id}/memoir/compilations",
                         headers=_auth(ftoken))
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# 7. 日报里的回忆文案
# ---------------------------------------------------------------------------

def test_memoir_sentences_wording():
    from app.services.digest_service import memoir_sentences

    assert memoir_sentences(None) == []
    assert memoir_sentences({"today": 0, "week": 0, "total": 0}) == []
    assert memoir_sentences({"today": 1, "total": 5})[0] == "今天留下了一段新回忆"
    assert "3 段" in memoir_sentences({"today": 3, "total": 5})[0]
    assert "这周" in memoir_sentences({"today": 0, "week": 4, "total": 8})[0]
    assert any("一共 12 段" in s for s in memoir_sentences({"today": 1, "total": 12}))


def test_fallback_summary_hides_zero_rounds():
    from app.services.digest_service import _fallback_summary, build_stats

    stats = build_stats([])
    assert stats["rounds"] == 0
    text = _fallback_summary(stats, {"today": 1, "total": 3})
    assert "0 轮" not in text
    assert "今天留下了一段新回忆" in text
    assert _fallback_summary(stats, None) == ""      # 什么都没有 → 空，不硬凑


@pytest.mark.asyncio
async def test_digest_payload_omits_memoir_when_all_zero():
    from app.services.digest_service import build_digest_payload

    payload = await build_digest_payload("王阿姨", [], "2026-10-15",
                                        memoir={"today": 0, "week": 0, "total": 0})
    assert "memoir" not in payload

    payload2 = await build_digest_payload("王阿姨", [], "2026-10-15",
                                         memoir={"today": 1, "week": 2, "total": 6})
    assert payload2["memoir"] == {"today": 1, "week": 2, "total": 6}


@pytest.mark.asyncio
async def test_count_family_visible_excludes_private_and_unarchived():
    await _bootstrap()
    elderly_id, _ = await _seed_elderly("m6_c1")
    await _seed_story(elderly_id, title="可见1")
    await _seed_story(elderly_id, title="可见2")
    await _seed_story(elderly_id, title="private的",
                      visibility="private", visibility_locked=True)
    await _seed_story(elderly_id, title="没留档的", status="draft")

    async with get_session_factory()() as session:
        repo = StoryRepo(session)
        assert await repo.count_family_visible(elderly_id) == 2
        # since 用未来时刻 → 一条都不算
        from datetime import datetime, timedelta
        assert await repo.count_family_visible(
            elderly_id, since=datetime.now() + timedelta(days=1)
        ) == 0


@pytest.mark.asyncio
async def test_digest_job_pushes_when_only_memory_was_recorded():
    """今天没怎么聊天、但认真留了一段回忆 → 也要有日报。"""
    await _bootstrap()
    elderly_id, token = await _seed_elderly("m6_j1")
    _, ftoken = await _seed_family("m6_j1b", bind_to=elderly_id)

    async with _client() as ac:
        # 先造一条 pending，再让老人确认留档（走真实接口，updated_at 才会刷新）
        async with get_session_factory()() as session:
            story = await StoryRepo(session).create(
                elderly_id, title="下乡", summary="十六岁下乡", status="pending_confirm",
            )
            await session.commit()
            sid = story.id
        assert (await ac.post(f"/api/v1/stories/{sid}/confirm",
                              headers=_auth(token))).status_code == 200

    from app.scheduler.jobs.daily_digest import daily_digest_job
    from app.services.digest_service import parse_digest_content
    from sqlalchemy import select
    from app.db.models import FamilyMessage

    await daily_digest_job()

    async with get_session_factory()() as session:
        rows = list((await session.execute(
            select(FamilyMessage).where(FamilyMessage.elderly_user_id == elderly_id)
        )).scalars().all())
    assert len(rows) == 1
    digest = parse_digest_content(rows[0].content)
    assert digest["memoir"] == {"today": 1, "week": 1, "total": 1}
    assert digest["summary"]                          # 有内容可看，不是空串
    assert "今天留下了一段新回忆" in digest["summary"]


@pytest.mark.asyncio
async def test_digest_job_ignores_private_story():
    """创伤 story 归档了也不该让家属从"新增 1 段"里感知到它存在（契约2）。"""
    await _bootstrap()
    elderly_id, token = await _seed_elderly("m6_j2")
    _, ftoken = await _seed_family("m6_j2b", bind_to=elderly_id)

    async with _client() as ac:
        async with get_session_factory()() as session:
            story = await StoryRepo(session).create(
                elderly_id, title="不愿提的事", status="pending_confirm",
                visibility="private", visibility_locked=True, avoid_flag=True,
            )
            await session.commit()
            sid = story.id
        await ac.post(f"/api/v1/stories/{sid}/confirm", headers=_auth(token))

    from app.scheduler.jobs.daily_digest import daily_digest_job
    from sqlalchemy import select
    from app.db.models import FamilyMessage

    await daily_digest_job()
    async with get_session_factory()() as session:
        rows = list((await session.execute(
            select(FamilyMessage).where(FamilyMessage.elderly_user_id == elderly_id)
        )).scalars().all())
    assert rows == []        # 没聊天 + 没有可见新回忆 → 不推日报
