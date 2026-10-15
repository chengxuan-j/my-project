"""M5 故事板 / 提示词编排测试。

重点：
- **契约6**：状态只到 `prompt_ready`，绝不出现渲染/视频；
- **契约4**：旁白必须第一人称、优先老人原话，模型改写过度就回退；
- **人物保护**：画面提示里的人脸描述逐短语剔除；
- **时长可控**：由代码分配，不采信 LLM（前端进度条要对得齐）；
- **降级**：LLM 不可用时线性拼接，包仍然完整可用。

不依赖 LLM Key（用 FakeClient 注入受控返回）。
"""
import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "test-secret"

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.json_utils import parse_json_loose  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.db.base import dispose_engine, get_session_factory, init_async_db  # noqa: E402
from app.main import app  # noqa: E402
from app.memoir import storyboard as SB  # noqa: E402
from app.repositories.account_repo import AccountRepo  # noqa: E402
from app.repositories.profile_repo import FamilyRepo  # noqa: E402
from app.repositories.story_repo import StoryRepo  # noqa: E402


class FakeStory:
    """只带编排需要的字段。"""

    def __init__(self, **kw):
        self.id = kw.get("id", 1)
        self.title = kw.get("title", "")
        self.summary = kw.get("summary", "")
        self.time_type = "relative"
        self.time_value = kw.get("time_value", "")
        self.time_confidence = 0.5
        self.time_inferred = False
        self.era_tags = kw.get("era_tags", [])
        self.place = kw.get("place", "")
        self.people = kw.get("people", [])
        self.emotion_tone = kw.get("emotion_tone", "平淡")
        self.completeness = 0.6
        self.status = "archived"
        self.visibility = "family"
        self.raw_dialogue = kw.get("raw_dialogue", [])


def _quote(text: str) -> list[dict]:
    return [{"role": "user", "content": text}, {"role": "assistant", "content": "嗯"}]


class FakeClient:
    """受控 LLM：返回预设文本，或抛错。"""

    is_configured = True

    def __init__(self, reply="", boom=False):
        self.reply = reply
        self.boom = boom
        self.calls = 0
        self.last_messages = None

    async def chat(self, messages, **kw):
        self.calls += 1
        self.last_messages = messages
        if self.boom:
            from app.llm.qwen_client import LLMError
            raise LLMError("no key")
        return self.reply


# ---------------------------------------------------------------------------
# 1. 时长分配（代码控制，不采信 LLM）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("count,total", [(1, 60), (2, 60), (3, 60), (4, 60), (6, 60), (12, 60)])
def test_allocate_durations_never_exceeds_total(count, total):
    durations = SB.allocate_durations(count, total)
    assert len(durations) == count
    assert sum(durations) <= total
    assert all(SB.MIN_SCENE_SECONDS <= d <= SB.MAX_SCENE_SECONDS for d in durations)


def test_allocate_durations_exact_when_possible():
    assert SB.allocate_durations(3, 60) == [20, 20, 20]
    assert sum(SB.allocate_durations(4, 60)) == 60
    assert SB.allocate_durations(0, 60) == []


# ---------------------------------------------------------------------------
# 2. 排序：与 M3 时代轴口径一致
# ---------------------------------------------------------------------------

def test_scene_plan_follows_era_axis():
    stories = [
        FakeStory(id=1, era_tags=["下岗改制"], title="下岗"),      # 1993
        FakeStory(id=2, era_tags=["知青年代"], title="下乡"),      # 1968
        FakeStory(id=3, era_tags=["改革开放初期"], title="当组长"),  # 1978
    ]
    plan = SB.build_scene_plan(stories, 60)
    assert [p["title"] for p in plan] == ["下乡", "当组长", "下岗"]


def test_scene_plan_caps_scene_count():
    stories = [FakeStory(id=i, era_tags=["知青年代"]) for i in range(30)]
    plan = SB.build_scene_plan(stories, 60)
    assert len(plan) == SB.MAX_SCENES


def test_original_quote_prefers_elderly_words():
    s = FakeStory(summary="摘要", raw_dialogue=_quote("我十六岁那年就下乡了"))
    assert SB.original_quote(s) == "我十六岁那年就下乡了"
    assert SB.original_quote(FakeStory(summary="只有摘要")) == "只有摘要"


# ---------------------------------------------------------------------------
# 3. 人物保护：人脸描述逐短语剔除
# ---------------------------------------------------------------------------

def test_visual_prompt_drops_only_offending_phrase():
    text = "北方冬日清晨的连队土房外景，寒风里的枯草，她的脸上带着笑，冷蓝色调，胶片质感"
    cleaned = SB.sanitize_visual_prompt(text)
    assert "脸" not in cleaned
    assert "连队土房外景" in cleaned          # 好描述保留
    assert "冷蓝色调" in cleaned


@pytest.mark.parametrize("bad", [
    "特写她的脸", "她面部的皱纹", "近景肖像", "close-up portrait of a woman", "五官清晰",
])
def test_visual_prompt_fully_banned_falls_back(bad):
    cleaned = SB.sanitize_visual_prompt(bad)
    assert "脸" not in cleaned
    assert cleaned == SB.VISUAL_FALLBACK


def test_visual_prompt_empty_uses_fallback():
    assert SB.sanitize_visual_prompt("") == SB.VISUAL_FALLBACK
    assert SB.sanitize_visual_prompt("   ") == SB.VISUAL_FALLBACK


# ---------------------------------------------------------------------------
# 4. 旁白：第一人称 + 优先老人原话（契约4）
# ---------------------------------------------------------------------------

def test_narration_falls_back_when_model_writes_third_person():
    original = "我十六岁那年就下乡了，去的黑龙江"
    narration, source = SB.pick_narration("他十六岁那年离开了家，去了很远的地方", original)
    assert narration == original and source == "original"


def test_narration_allows_omitted_subject():
    """中文主语省略是常态：只要不是把老人写成第三人称，就该保留改写。

    真实语料里「那时候买米买面都得要粮票」就是老人原话，硬要求含「我」
    会误杀一大片合格旁白——这条是那次回归的守卫。
    """
    original = "那时候买米买面都得要粮票，一个月就那么点，得算着吃"
    narration, source = SB.pick_narration(
        "那时候买米买面都得要粮票，一个月就那么点，得算着吃。", original
    )
    assert source == "model"
    assert "我" not in narration


def test_narration_allows_third_person_present_in_original():
    """原话里本来就有「他」（指老伴），模型照用不算违约。"""
    original = "我跟他是在厂里认识的，同事介绍的"
    narration, source = SB.pick_narration("我跟他是在厂里认识的，同事介绍的。", original)
    assert source == "model"


def test_introduces_third_person_definition():
    assert SB.introduces_third_person("她十六岁就下乡了", "我十六岁就下乡了") is True
    assert SB.introduces_third_person("老人当年在纺织厂", "我在纺织厂") is True
    # 原话里已有该词 → 不算引入
    assert SB.introduces_third_person("我跟他认识", "我跟他是在厂里认识的") is False


def test_narration_falls_back_when_model_strays_too_far():
    original = "我十六岁那年就下乡了，去的黑龙江生产建设兵团"
    narration, source = SB.pick_narration("那年头日子过得紧巴巴的", original)
    assert source == "original"


def test_narration_keeps_close_paraphrase():
    original = "我十六岁那年就下乡了，去的黑龙江"
    narration, source = SB.pick_narration("我十六岁那年就下乡了，去的黑龙江。", original)
    assert source == "model"


def test_narration_empty_falls_back_to_original():
    narration, source = SB.pick_narration("", "我那时候在纺织厂")
    assert narration == "我那时候在纺织厂" and source == "original"


def test_similarity_definition():
    assert SB.similarity("我去过黑龙江", "我去过黑龙江") == 1.0
    assert SB.similarity("", "abc") == 0.0


# ---------------------------------------------------------------------------
# 5. 后校验：时长/出处/免责声明一律由代码兜底
# ---------------------------------------------------------------------------

def _plan():
    return SB.build_scene_plan(
        [FakeStory(id=7, title="下乡", era_tags=["知青年代"], place="黑龙江",
                   raw_dialogue=_quote("我十六岁那年就下乡了，去的黑龙江"))],
        60,
    )


def test_assemble_forces_disclaimer_and_evidence():
    pkg = SB.assemble_package({"title": "我的十年"}, _plan())
    assert pkg["disclaimer"] == SB.DEFAULT_DISCLAIMER      # 模型没给 → 补默认
    scene = pkg["scenes"][0]
    assert scene["source_evidence"] == "我十六岁那年就下乡了，去的黑龙江"
    assert scene["story_id"] == 7


def test_assemble_ignores_llm_duration():
    """模型乱给时长也不能信——时长由代码分配，否则前端进度条对不齐。"""
    pkg = SB.assemble_package(
        {"scenes": [{"story_id": 7, "narration": "我十六岁那年就下乡了，去的黑龙江",
                     "visual_prompt": "冬日连队外景", "duration_seconds": 999}]},
        _plan(),
    )
    assert pkg["scenes"][0]["duration_seconds"] == 25
    assert pkg["total_seconds"] == 25
    assert pkg["requested_seconds"] == 60      # 实际短于请求值时如实告知


def test_assemble_keeps_every_scene_even_if_model_drops_one():
    stories = [FakeStory(id=1, title="A"), FakeStory(id=2, title="B")]
    plan = SB.build_scene_plan(stories, 60)
    pkg = SB.assemble_package({"scenes": [{"story_id": 2, "narration": "我在说B"}]}, plan)
    assert [s["story_id"] for s in pkg["scenes"]] == [1, 2]   # 一条不少


def test_assemble_rejects_bad_perspective():
    pkg = SB.assemble_package({"perspective": "god_view"}, _plan())
    assert pkg["perspective"] == "first_person"


def test_assemble_empty_plan_is_safe():
    pkg = SB.assemble_package(None, [])
    assert pkg["scenes"] == []
    assert pkg["disclaimer"] == SB.DEFAULT_DISCLAIMER
    assert pkg["total_seconds"] == 0


def test_contract6_no_render_engine():
    pkg = SB.assemble_package(None, _plan())
    assert pkg["render_engine"] is None


# ---------------------------------------------------------------------------
# 6. 编排器：正常 + 两种降级
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_builder_uses_llm_output():
    reply = (
        '{"title": "黑龙江的雪", "perspective": "first_person", "scenes": '
        '[{"story_id": 7, "narration": "我十六岁那年就下乡了，去的黑龙江", '
        '"visual_prompt": "冬日连队土房外景，冷蓝色调，胶片质感"}]}'
    )
    builder = SB.StoryboardBuilder(client=FakeClient(reply))
    pkg = await builder.build(
        [FakeStory(id=7, title="下乡", era_tags=["知青年代"],
                   raw_dialogue=_quote("我十六岁那年就下乡了，去的黑龙江"))]
    )
    assert pkg["llm_used"] is True
    assert pkg["title"] == "黑龙江的雪"
    assert "连队土房外景" in pkg["scenes"][0]["visual_prompt"]
    # 提示词里明确写了不许描述人脸
    assert "不要描述人脸" in builder.client.last_messages[0]["content"]


@pytest.mark.asyncio
async def test_builder_degrades_when_llm_unavailable():
    builder = SB.StoryboardBuilder(client=FakeClient(boom=True))
    pkg = await builder.build(
        [FakeStory(id=7, title="下乡", raw_dialogue=_quote("我十六岁那年就下乡了"))]
    )
    assert pkg["llm_used"] is False
    scene = pkg["scenes"][0]
    assert scene["narration"] == "我十六岁那年就下乡了"   # 线性降级用原话
    assert scene["visual_prompt"] == SB.VISUAL_FALLBACK
    assert pkg["disclaimer"] == SB.DEFAULT_DISCLAIMER


@pytest.mark.asyncio
async def test_builder_degrades_on_non_json():
    builder = SB.StoryboardBuilder(client=FakeClient("抱歉，我无法完成。"))
    pkg = await builder.build([FakeStory(id=7, title="下乡")])
    assert pkg["llm_used"] is False
    assert pkg["scenes"][0]["visual_prompt"] == SB.VISUAL_FALLBACK


@pytest.mark.asyncio
async def test_builder_empty_input():
    builder = SB.StoryboardBuilder(client=FakeClient("{}"))
    pkg = await builder.build([])
    assert pkg["scenes"] == [] and pkg["llm_used"] is False


def test_parse_json_loose_handles_fenced_json():
    assert parse_json_loose('```json\n{"a": 1}\n```') == {"a": 1}


# ---------------------------------------------------------------------------
# 7. 接口层
# ---------------------------------------------------------------------------

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
            raw_dialogue=_quote("我十六岁那年就下乡了，去的黑龙江"),
        )
        defaults.update(kw)
        story = await StoryRepo(session).create(user_id, **defaults)
        await session.commit()
        return story.id


@pytest.mark.asyncio
async def test_create_compilation_requires_elderly():
    await _bootstrap()
    elderly_id, _ = await _seed_elderly("m5_e1")
    _, family_token = await _seed_family("m5_f1", bind_to=elderly_id)
    async with _client() as ac:
        assert (await ac.post("/api/v1/memoir/compilations",
                              json={"title": "x"})).status_code == 401
        assert (await ac.post("/api/v1/memoir/compilations", headers=_auth(family_token),
                              json={"title": "x"})).status_code == 403


@pytest.mark.asyncio
async def test_create_compilation_without_archived_stories_conflicts():
    await _bootstrap()
    _, token = await _seed_elderly("m5_e2")
    await _seed_story("m5_e2", status="pending_confirm")
    async with _client() as ac:
        r = await ac.post("/api/v1/memoir/compilations", headers=_auth(token),
                          json={"title": "x"})
        assert r.status_code == 409


@pytest.mark.asyncio
async def test_create_compilation_yields_prompt_ready():
    """无 Key 时走线性降级，但状态与包结构仍然完整。"""
    await _bootstrap()
    elderly_id, token = await _seed_elderly("m5_e3")
    sid = await _seed_story(elderly_id)

    async with _client() as ac:
        r = await ac.post("/api/v1/memoir/compilations", headers=_auth(token),
                          json={"title": "我的一段日子", "total_seconds": 40})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "prompt_ready"     # 契约6：止步于此
        assert body["video_url"] is None
        assert body["rendered"] is False
        assert body["story_ids"] == [sid]
        pkg = body["prompt_package"]
        assert pkg["disclaimer"]
        assert pkg["scenes"][0]["source_evidence"] == "我十六岁那年就下乡了，去的黑龙江"

        # 列表与详情
        listing = (await ac.get("/api/v1/memoir/compilations", headers=_auth(token))).json()
        assert [c["id"] for c in listing] == [body["id"]]
        detail = (await ac.get(f"/api/v1/memoir/compilations/{body['id']}",
                               headers=_auth(token))).json()
        assert detail["id"] == body["id"]

        # 删除
        assert (await ac.delete(f"/api/v1/memoir/compilations/{body['id']}",
                                headers=_auth(token))).status_code == 200
        assert (await ac.get(f"/api/v1/memoir/compilations/{body['id']}",
                             headers=_auth(token))).status_code == 404


@pytest.mark.asyncio
async def test_compilation_cross_user_isolated():
    await _bootstrap()
    owner_id, _ = await _seed_elderly("m5_e4")
    await _seed_story(owner_id)
    _, other_token = await _seed_elderly("m5_e5")
    async with _client() as ac:
        r = await ac.post("/api/v1/memoir/compilations", headers=_auth(other_token),
                          json={"title": "x"})
        assert r.status_code == 409  # 他自己没有可编排的故事


@pytest.mark.asyncio
async def test_family_read_filters_scenes_by_current_visibility():
    """契约2 补丁：编排快照不会自动更新，家属读取时按**当下**可见性再筛。"""
    await _bootstrap()
    elderly_id, token = await _seed_elderly("m5_e6")
    keep = await _seed_story(elderly_id, title="能看的", visibility="family")
    secret = await _seed_story(elderly_id, title="别给人看", visibility="family")
    _, family_token = await _seed_family("m5_f6", bind_to=elderly_id)

    async with _client() as ac:
        comp = (await ac.post("/api/v1/memoir/compilations", headers=_auth(token),
                              json={"title": "合片"})).json()
        assert set(comp["story_ids"]) == {keep, secret}

        # 家属现在能看到两段
        full = (await ac.get(
            f"/api/v1/family/elderly/{elderly_id}/memoir/compilations/{comp['id']}",
            headers=_auth(family_token))).json()
        assert len(full["prompt_package"]["scenes"]) == 2

        # 老人把其中一条收回可见性（走仓储，等价于后续可能的接口）
        async with get_session_factory()() as session:
            await StoryRepo(session).set_visibility(secret, "private")
            await session.commit()

        filtered = (await ac.get(
            f"/api/v1/family/elderly/{elderly_id}/memoir/compilations/{comp['id']}",
            headers=_auth(family_token))).json()
        ids = {s["story_id"] for s in filtered["prompt_package"]["scenes"]}
        assert ids == {keep}


@pytest.mark.asyncio
async def test_family_read_404_when_all_scenes_hidden():
    await _bootstrap()
    elderly_id, token = await _seed_elderly("m5_e7")
    sid = await _seed_story(elderly_id, visibility="family")
    _, family_token = await _seed_family("m5_f7", bind_to=elderly_id)

    async with _client() as ac:
        comp = (await ac.post("/api/v1/memoir/compilations", headers=_auth(token),
                              json={"title": "合片"})).json()
        async with get_session_factory()() as session:
            story = await StoryRepo(session).get(sid)
            story.visibility = "private"
            story.visibility_locked = True
            await session.commit()

        r = await ac.get(
            f"/api/v1/family/elderly/{elderly_id}/memoir/compilations/{comp['id']}",
            headers=_auth(family_token),
        )
        assert r.status_code == 404   # 整片被收回 → 对家属等同于不存在


@pytest.mark.asyncio
async def test_family_read_requires_binding():
    await _bootstrap()
    elderly_id, token = await _seed_elderly("m5_e8")
    await _seed_story(elderly_id)
    _, family_token = await _seed_family("m5_f8")   # 未绑定
    async with _client() as ac:
        comp = (await ac.post("/api/v1/memoir/compilations", headers=_auth(token),
                              json={"title": "合片"})).json()
        r = await ac.get(
            f"/api/v1/family/elderly/{elderly_id}/memoir/compilations/{comp['id']}",
            headers=_auth(family_token),
        )
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_family_has_no_write_path_for_compilations():
    """契约1：家属只能读，不能创建也不能删。

    M6 之后家属端**新增了** `GET .../compilations`（列表），所以集合路径现在
    是"存在但只挂 GET"——POST 应当是 405（方法不允许），而不是 404。
    这正是我们想要的信号：路径在、能力不在。

    项路径同理：只注册了 GET，POST / DELETE 一律 405。
    家属在 M6 唯一能写的是**照片**（另行验证），编排始终是老人专属。
    """
    await _bootstrap()
    elderly_id, _ = await _seed_elderly("m5_e9")
    _, family_token = await _seed_family("m5_f9", bind_to=elderly_id)
    base = f"/api/v1/family/elderly/{elderly_id}/memoir/compilations"

    async with _client() as ac:
        # 列表可读（家属能看已排好的短片）
        assert (await ac.get(base, headers=_auth(family_token))).status_code == 200
        # 但写不了：集合路径只有 GET
        assert (await ac.post(base, headers=_auth(family_token),
                              json={"title": "x"})).status_code == 405
        # 项路径也只有 GET
        assert (await ac.post(f"{base}/1", headers=_auth(family_token),
                              json={"title": "x"})).status_code == 405
        assert (await ac.delete(f"{base}/1", headers=_auth(family_token))).status_code == 405
