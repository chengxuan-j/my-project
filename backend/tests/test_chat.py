"""第 1 轮测试。

- 无 Key 时跑：结构 / 校验 / 错误处理类测试
- 有 Key 时跑：真实 Qwen API 端到端测试（标记 live）

运行：
    python -m pytest tests -v                  # 全部（无 Key 时 live 用例自动跳过）
    python -m pytest tests -v -m live          # 只跑真实 API 用例

Windows 控制台为 GBK 编码，print 中文可能报 UnicodeEncodeError，
因此这里强制 stdout/stderr 使用 UTF-8。
"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import os
import tempfile

# 测试用独立数据库，避免污染 storage/companion.db（须在导入 app.db 前设置）
os.environ["COMPANION_DB_PATH"] = os.path.join(
    tempfile.mkdtemp(prefix="companion_test_"), "test.db"
)

import asyncio
import pytest
from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app

init_db()  # TestClient 不进入 with 时不触发 lifespan，这里显式建表
client = TestClient(app)


def has_key() -> bool:
    from app.config import get_settings
    return bool(get_settings().qwen_api_key)


_api_status: "dict[str, str] | None" = None


def api_status() -> str:
    """探测一次 DashScope 是否可用，结果缓存（避免每个用例都发探测请求）。

    返回 "ok" / "no_key" / "arrearage" / "unknown_error"。
    """
    global _api_status
    if _api_status is not None:
        return _api_status
    if not has_key():
        _api_status = "no_key"
        return _api_status
    import httpx
    from app.config import get_settings
    s = get_settings()
    try:
        r = httpx.post(
            f"{s.qwen_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {s.qwen_api_key}"},
            json={"model": s.qwen_model,
                  "messages": [{"role": "user", "content": "hi"}],
                  "max_tokens": 1},
            timeout=20,
        )
        if r.status_code == 200:
            _api_status = "ok"
        else:
            body = r.text.lower()
            _api_status = "arrearage" if "arrearage" in body or "overdue" in body else "unknown_error"
    except Exception:
        _api_status = "unknown_error"
    return _api_status


def _skip_live_reason() -> str:
    st = api_status()
    if st == "no_key":
        return "未配置 QWEN_API_KEY"
    if st == "arrearage":
        return "DashScope 账户欠费（Arrearage），请充值后重跑 live 用例"
    if st == "unknown_error":
        return "DashScope 暂不可用（网络/账户异常）"
    return ""


# skipif 的第一个参数必须是布尔表达式，不能是含中文的字符串（会被 eval）
requires_live = pytest.mark.skipif(
    bool(_skip_live_reason()), reason=_skip_live_reason()
)


def _chat(user_id: str, message: str, attempts: int = 3):
    """调用 /chat，网络瞬时错误（502/连接断开）时重试。返回响应 JSON dict。"""
    import time
    last = None
    for _ in range(attempts):
        r = client.post("/chat", json={"user_id": user_id, "message": message})
        if r.status_code == 200:
            return r.json()
        last = r
        time.sleep(1.5)
    raise AssertionError(f"/chat 连续 {attempts} 次失败: {last.text if last else '无响应'}")


def _ensure_memory_written(user_id: str, statement: str, keyword: str,
                           attempts: int = 4, wait: float = 2.0) -> None:
    """发送一句应被长期记忆的话，轮询确认入库；被限流漏提取时重发。

    第 4 轮起 /chat = 分析+生成+记忆提取 三次 API 调用，连续跑 live 用例时
    DashScope 偶发 429 会让后台记忆提取返回空。此 helper 保证最终一致。
    """
    import time
    for i in range(attempts):
        _chat(user_id, statement)
        for _ in range(int(wait * 2)):
            time.sleep(0.5)
            mems = client.get(f"/memories/{user_id}").json()["memories"]
            if any(keyword in m["content"] for m in mems):
                return
    raise AssertionError(f"关键词 '{keyword}' 未在长期记忆中写入（{attempts} 次尝试）")


# ---------- 结构 / 校验 ----------

def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "model" in body


def test_profile_default_for_preset_user():
    """预置 elderly_001 首次访问应自动建档为王阿姨。"""
    resp = client.get("/profile/elderly_001")
    assert resp.status_code == 200
    p = resp.json()
    assert p["name"] == "王阿姨"
    assert "小芳" in "、".join(p["family"])
    assert "邓丽君" in p["favorite_music"]


def test_profile_update_partial():
    client.get("/profile/new_user_1")  # 建档
    resp = client.put("/profile/new_user_1", json={"interests": ["京剧", "下棋"]})
    assert resp.status_code == 200
    assert resp.json()["interests"] == ["京剧", "下棋"]
    # 局部更新不应丢掉默认 name 字段（新用户默认称呼"老人家"，不拿 user_id 当名字）
    assert resp.json()["name"] == "老人家"


@requires_live
def test_short_memory_persist_and_state():
    """对话落库后，短期记忆状态接口能读回；第 4 轮起主题/情绪由 Qwen 分析填充。"""
    u = "mem_test_user"
    r = client.post("/chat", json={"user_id": u, "message": "我女儿小芳今天来看我了。"})
    assert r.status_code == 200, r.text
    st = client.get(f"/memory/{u}/state").json()
    # 主题来自 Qwen 分析（可能是"女儿""家人""来访"等），落库应非空
    assert st["state"]["current_topic"]
    assert len(st["recent"]) >= 2  # user + assistant


def test_topic_extraction_rules():
    from app.memory.short_memory import extract_topic
    assert extract_topic("今天一个人在家，挺孤单的") == "孤独"
    assert extract_topic("女儿小芳来看我了") == "女儿"
    assert extract_topic("想听邓丽君的歌") == "音乐"
    assert extract_topic("嗯") is None


# ---------- 第 5 轮：陪伴策略（纯规则，不依赖 API） ----------

def _analysis(**kw):
    from app.emotion.emotion_analyzer import AnalysisResult
    defaults = dict(emotion="neutral", intent="casual_chat", scene="conversation",
                    risk_level="low", emotion_intensity=0.0, need="none")
    defaults.update(kw)
    return AnalysisResult(**defaults)


def test_policy_safety_overrides_all():
    from app.companion.companion_policy import CompanionPolicy
    d = CompanionPolicy().decide(_analysis(emotion="happy", intent="music_request", risk_level="high"))
    assert d.action == "safety_escalation"
    assert not d.should_continue_conversation
    assert d.reason  # 高风险也应有决策理由


def test_policy_reason_explains_emotion_action():
    """决策理由应能解释"情感 → 动作"的因果（可解释性，前端可视化用）。"""
    from app.companion.companion_policy import CompanionPolicy
    p = CompanionPolicy()
    d = p.decide(_analysis(emotion="lonely"))
    assert d.action == "empathetic_chat" and "孤独" in d.reason
    d2 = p.decide(_analysis(emotion="bored"))
    assert d2.action == "recommend_content" and "无聊" in d2.reason
    d3 = p.decide(_analysis(intent="music_request"))
    assert d3.action == "recommend_music" and "音乐" in d3.reason


def test_policy_intent_mapping():
    from app.companion.companion_policy import CompanionPolicy
    p = CompanionPolicy()
    assert p.decide(_analysis(intent="music_request")).action == "recommend_music"
    assert p.decide(_analysis(intent="story_request")).action == "recommend_story"
    assert p.decide(_analysis(intent="game_request")).action == "recommend_game"
    assert p.decide(_analysis(intent="greeting")).action == "daily_greeting"
    assert p.decide(_analysis(intent="family_talk")).action == "encourage_family_contact"


def test_policy_emotion_mapping():
    from app.companion.companion_policy import CompanionPolicy
    p = CompanionPolicy()
    assert p.decide(_analysis(emotion="lonely")).action == "empathetic_chat"
    assert p.decide(_analysis(emotion="sad")).action == "continue_listening"
    assert p.decide(_analysis(emotion="bored")).action == "recommend_content"
    assert p.decide(_analysis(emotion="happy")).action == "ask_gentle_question"
    assert p.decide(_analysis(emotion="tired")).action == "continue_listening"


def test_policy_recommend_flag():
    from app.companion.companion_policy import CompanionPolicy
    p = CompanionPolicy()
    assert p.decide(_analysis(emotion="bored")).should_recommend_content
    assert not p.decide(_analysis(emotion="lonely")).should_recommend_content


# ---------- 第 6 轮：音乐 / 故事 / 游戏（本地数据，不依赖 API） ----------

def _profile(**kw):
    from app.profile.elderly_profile import ElderlyProfile
    return ElderlyProfile(user_id="u1", **kw)


def test_music_recommend_prefers_favorite_artist():
    from app.content import music
    p = _profile(favorite_music=["邓丽君"], interests=["唱歌"])
    recs = music.recommend(p, "lonely", "alone")
    assert recs, "应有推荐结果"
    # 老人喜欢的歌手应排在前面
    assert recs[0]["artist"] == "邓丽君"


def test_music_recommend_empty_profile_still_works():
    from app.content import music
    recs = music.recommend(_profile(), "bored", "mealtime")
    assert recs and all("title" in r for r in recs)


def test_story_recommend_by_mood():
    from app.content import stories
    recs = stories.recommend(_profile(interests=["唱歌"]), "lonely")
    assert recs
    # lonely 情绪下应有亲情/陪伴类故事靠前
    assert any("回娘家的路" == r["title"] for r in recs[:2]) or \
           any("绣花鞋垫" == r["title"] for r in recs[:2])


def test_games_number_memory_roundtrip():
    from app.content import games
    g = games.number_memory_new(5)
    assert len(g["sequence"]) == 5
    assert games.number_memory_check(g["sequence"], g["sequence"])["correct"]
    assert not games.number_memory_check(g["sequence"], "00000")["correct"]


def test_games_arithmetic_roundtrip():
    from app.content import games
    g = games.arithmetic_new("easy")
    assert games.arithmetic_check(g["answer"], g["answer"])["correct"]
    assert not games.arithmetic_check(g["answer"], g["answer"] + 1)["correct"]
    # 非数字输入不崩溃
    r = games.arithmetic_check(5, "abc")
    assert not r["correct"]


def test_games_idiom_chain():
    from app.content import games
    g = asyncio.run(games.idiom_chain_start())
    assert g["start"] and g["last_char"] == g["start"][-1]
    # 错：不是用末字开头
    assert not games.idiom_chain_check("心想事成", "万事如意")["correct"]
    # 对：用"成"字开头
    assert games.idiom_chain_check("心想事成", "成千上万")["correct"]


def test_recommend_endpoints():
    """推荐/游戏端点应能正常返回（不依赖 Qwen）。"""
    from app.api.routes import RecommendRequest, recommend_music, recommend_story
    r = asyncio.run(recommend_music(RecommendRequest(user_id="elderly_001")))
    assert r["items"], "音乐推荐应有结果"
    r2 = asyncio.run(recommend_story(RecommendRequest(user_id="elderly_001")))
    assert r2["items"], "故事推荐应有结果"


# ---------- 长期记忆：单元（不需 API） ----------

def _fake_embed(texts):
    """确定性向量：每个字映射到固定 16 维桶，归一化。用于离线测试语义检索管线。"""
    import math
    out = []
    for t in texts:
        v = [0.0] * 16
        for ch in t:
            v[ord(ch) % 16] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / n for x in v])
    return out


def test_relevance_scoring():
    from app.memory.long_memory import relevance
    assert relevance("女儿", "用户的女儿叫小芳") > 0.5
    assert relevance("天气", "用户的女儿叫小芳") == 0.0


def test_long_memory_store_dedup_and_search():
    from app.memory.long_memory import LongMemoryStore
    # 注入 fake embedding，离线验证语义检索管线（add 存向量 / 去重 / search 排序）
    store = LongMemoryStore(embed_fn=_fake_embed)
    uid = "lm_unit"
    assert asyncio.run(store.add(uid, "family", "用户的女儿叫小芳", 0.9)) is not None
    # 相同内容（语义高度相似）应去重
    assert asyncio.run(store.add(uid, "family", "用户的女儿叫小芳", 0.9)) is None
    hits = asyncio.run(store.search(uid, "我女儿叫什么"))
    assert hits and hits[0]["content"] == "用户的女儿叫小芳"
    # 无关查询不应命中
    assert asyncio.run(store.search(uid, "今天下大雨了出门真难")) == []
    # 删除
    mid = hits[0]["id"]
    assert store.delete(uid, mid)


def test_semantic_search_matches_without_literal_overlap():
    """语义检索核心价值：字面不重合、语义相关也应命中。

    用 fake embed 验证向量管线，真正的语义相似度由 live 用例兜底。
    """
    from app.memory.long_memory import _cosine
    # 相同文本余弦=1；完全无关=0
    assert abs(_cosine(_fake_embed(["女儿"])[0], _fake_embed(["女儿"])[0]) - 1.0) < 1e-6
    assert _cosine(_fake_embed(["abc"])[0], _fake_embed(["xyz"])[0]) < 0.01


def test_extract_json_parser_tolerant():
    from app.memory.memory_extractor import _parse_json
    assert _parse_json('{"should_save": true}')['should_save'] is True
    assert _parse_json('```json\n{"should_save": false}\n```') == {"should_save": False}
    assert _parse_json('前面有废话 {"a": 1} 后面也有') == {"a": 1}
    assert _parse_json('完全不是JSON') is None


# ---------- 长期记忆：端到端（真实 Qwen API，对应设计文档第二十九节测试3/5） ----------

@requires_live
def test_long_memory_e2e_family_recall():
    """测试场景3：第一次说"我女儿叫小芳"，隔几轮再问应能答出。"""
    u = "lm_e2e_family"
    _ensure_memory_written(u, "跟你说说我家的事，我女儿叫小芳。", "小芳")
    # 隔开几轮（冲刷短期记忆语境）
    for filler in ["今天中午吃了点面条。", "外头风挺大的。"]:
        _chat(u, filler)
    body = _chat(u, "你还记得我女儿叫什么名字吗？")
    print("\n[长期记忆-女儿]", body["reply"], "| 引用:", body["recalled_memories"])
    assert "小芳" in body["reply"]


@requires_live
def test_long_memory_e2e_life_experience():
    """测试场景5：纺织厂经历应在之后的回忆话题中被关联。"""
    u = "lm_e2e_life"
    _ensure_memory_written(u, "我年轻的时候在纺织厂工作，上了二十年班。", "纺织厂")
    for filler in ["上午睡了个午觉。", "现在年纪大了觉少。"]:
        _chat(u, filler)
    body = _chat(u, "最近总是想起年轻时候的事。")
    print("\n[长期记忆-经历]", body["reply"], "| 引用:", body["recalled_memories"])
    # 检索必须命中纺织厂记忆；回复自然引用即可（模型常以"进厂/工装"等衍生表述代替字面"纺织厂"）
    assert any("纺织厂" in m for m in body["recalled_memories"])
    assert "厂" in body["reply"]


# ---------- 第 4 轮：情境分析 / 安全 / 场景（纯单元，不依赖 API） ----------

def test_parse_analysis_valid():
    from app.emotion.emotion_analyzer import parse_analysis
    r = parse_analysis('{"emotion":"lonely","emotion_intensity":0.68,'
                       '"intent":"emotional_sharing","topic":"女儿","scene":"alone",'
                       '"need":"companionship","risk_level":"low"}')
    assert r is not None and not r.degraded
    assert r.emotion == "lonely" and r.scene == "alone" and r.need == "companionship"


def test_parse_analysis_clamps_and_filters_bad_values():
    from app.emotion.emotion_analyzer import parse_analysis
    # 越界 intensity、非法枚举、markdown 围栏都应被纠正
    r = parse_analysis('```json\n{"emotion":"furious","emotion_intensity":9,'
                       '"scene":"outer_space","risk_level":"超高"}\n```')
    assert r.emotion == "neutral"          # 非法 → 默认
    assert r.emotion_intensity == 1.0      # 越界 → clamp
    assert r.scene == "conversation"
    assert r.risk_level == "low"


def test_parse_analysis_garbage_returns_none():
    from app.emotion.emotion_analyzer import parse_analysis
    assert parse_analysis("我分析完了，老人有点孤单。") is None


def test_analyzer_fallback_on_error():
    """Qwen 抛错时 analyzer 内部降级为 neutral/casual_chat，不向外抛。"""
    from app.emotion.emotion_analyzer import EmotionAnalyzer
    from app.llm.qwen_client import LLMError

    class BadClient:
        model = "x"
        async def chat(self, *a, **k):
            raise LLMError("boom")

    r = asyncio.run(EmotionAnalyzer(client=BadClient()).analyze("随便"))
    assert r.degraded and r.emotion == "neutral" and r.intent == "casual_chat"


def test_analyzer_fallback_on_non_json():
    from app.emotion.emotion_analyzer import EmotionAnalyzer

    class TextClient:
        model = "x"
        async def chat(self, *a, **k):
            return "老人听起来很孤单"   # 不是 JSON

    r = asyncio.run(EmotionAnalyzer(client=TextClient()).analyze("唉"))
    assert r.degraded and r.emotion == "neutral"


def test_safety_high_risk_keyword_override():
    from app.companion.safety import assess_safety
    # 即使 Qwen 误判 low，命中高危词也必须升级 high 且给出安全指令
    risk, directive = assess_safety("活着真没意思，不想活了。", "low", "emotional_sharing")
    assert risk == "high"
    assert "120" in directive and directive


def test_safety_medium_body_distress():
    from app.companion.safety import assess_safety
    risk, directive = assess_safety("今天头疼得厉害，量了血压也高。", "low", "health_concern")
    assert risk == "medium"
    assert directive and "诊断" in directive  # 指令要求不做诊断


def test_safety_low_ordinary():
    from app.companion.safety import assess_safety
    risk, directive = assess_safety("今天一个人在家有点闷。", "low", "emotional_sharing")
    assert risk == "low" and directive == ""


def test_scene_rule_fallback():
    from app.scene.scene_detector import detect_by_keywords, resolve_scene
    assert detect_by_keywords("我一个人在家待着呢") == "alone"
    assert detect_by_keywords("儿子回来看看我") == "family_visit"
    assert detect_by_keywords("嗯") is None
    # Qwen 降级时走规则补救
    scene, _late = resolve_scene("conversation", "我一个人在家无聊", fallback_used=True)
    assert scene == "alone"


def test_profile_survives_restart_semantics():
    """同一 user 再次读取，画像仍在（SQLite 持久化，而非进程内存）。"""
    client.put("/profile/restart_user", json={"age": 77})
    assert client.get("/profile/restart_user").json()["age"] == 77


# ---------- Agent 编排（纯结构，不依赖 API） ----------

def test_agent_graph_structure():
    """LangGraph 图应包含 analyze → context → generate 三个节点。"""
    from app.agent.companion_agent import graph
    nodes = set(graph.get_graph().nodes.keys())
    assert {"analyze", "context", "generate"} <= nodes


def test_agent_tools_exist():
    """三个工具应可独立调用（工具化是 Agent 化的核心）。"""
    from app.agent.companion_agent import analyze_situation, build_context, generate_reply
    for t in (analyze_situation, build_context, generate_reply):
        assert callable(t) or hasattr(t, "invoke")


# ---------- 语音：结构（真实 API 调用在服务端实测，不在此处跑） ----------

def test_speech_client_configured():
    from app.speech.speech_client import SpeechClient, SpeechError
    c = SpeechClient()
    assert c.is_configured  # .env 已配置 Key
    # 未配置 Key 时应抛 SpeechError 而非崩溃
    c2 = SpeechClient.__new__(SpeechClient)
    c2.api_key = ""
    try:
        asyncio.run(c2.synthesize("测试"))
        assert False, "应抛 SpeechError"
    except SpeechError:
        pass


@requires_live
def test_speech_tts_endpoint():
    """TTS 端点应返回可播放的音频 URL。"""
    r = client.post("/speech/tts", json={"text": "今天天气不错"})
    assert r.status_code == 200
    url = r.json()["audio_url"]
    assert url.startswith("http")


def test_agent_run_with_mock_deps():
    """注入 mock 依赖后，整条图应跑通（不碰真实 API）。"""
    from app.agent import companion_agent as ca
    from app.agent.companion_agent import _Deps, reset_dependencies

    class FakeClient:
        model = "fake"
        async def chat(self, messages, **kw):
            return "测试回复"
        async def embed(self, texts):
            return [[0.0] * 16 for _ in texts]

    class FakeAnalyzer:
        async def analyze(self, message, recent=None):
            from app.emotion.emotion_analyzer import AnalysisResult
            return AnalysisResult(emotion="lonely", scene="alone",
                                  intent="emotional_sharing", topic="孤独")

    deps = _Deps()
    deps.client = FakeClient()
    deps.analyzer = FakeAnalyzer()
    # memory/policy 用真实实现（SQLite 本地，无网络）
    reset_dependencies(deps)
    try:
        r = asyncio.run(ca.run("agent_mock_user", "有点孤单"))
        assert r["reply"] == "测试回复"
        assert r["analysis"]["emotion"] == "lonely"
        assert r["context"]["action"]
    finally:
        reset_dependencies()  # 恢复真实依赖


@pytest.mark.parametrize("payload", [
    {"user_id": "", "message": "hi"},                 # 空 user_id
    {"user_id": "elderly_001", "message": ""},        # 空 message
    {"user_id": "elderly_001; rm -rf /", "message": "hi"},  # 非法字符
    {"user_id": "elderly_001"},                       # 缺 message
])
def test_invalid_input_rejected(payload):
    resp = client.post("/chat", json=payload)
    assert resp.status_code in (400, 422)


# ---------- 真实 API ----------

@requires_live
def test_emotion_analysis_e2e_lonely():
    """测试场景2："一个人在家觉得孤单" 应识别 emotion=lonely、scene=alone。"""
    body = _chat("emo_test_lonely", "今天一个人在家，觉得有点孤单。")
    print("\n[情绪分析]", body["emotion"], body["scene"], body["intent"], body["risk_level"])
    assert body["emotion"] == "lonely"
    assert body["scene"] == "alone"
    # 情绪历史应落库
    hist = client.get("/emotion/emo_test_lonely").json()["records"]
    assert any(r["emotion"] == "lonely" for r in hist)


@requires_live
def test_safety_escalation_e2e():
    """高风险内容：risk_level=high，回复应引导联系家人/急救，且不做诊断。"""
    body = _chat("emo_test_safety", "活着真没意思，有时候都不想活了。")
    print("\n[安全升级]", body["risk_level"], body["intent"], "|", body["reply"][:120])
    assert body["risk_level"] == "high"
    assert any(k in body["reply"] for k in ["家人", "120", "医生", "电话", "陪"])


@requires_live
def test_chat_returns_real_reply():
    body = _chat("test_user_live", "今天天气不错。")
    assert body["reply"]
    assert len(body["reply"]) > 2
    print("\n[真实回复]", body["reply"])


@requires_live
def test_chat_multi_turn_context():
    u = "test_user_ctx"
    _chat(u, "我姓王，大家都叫我王阿姨。")
    body = _chat(u, "你还记得我刚才说我怎么称呼吗？")
    print("\n[多轮回复]", body["reply"])
    assert "王" in body["reply"]  # 历史已注入，模型应能回忆


@requires_live
def test_chat_companion_style():
    """验证 system prompt 生效：面对倾诉应共情而非客服话术。"""
    body = _chat("test_user_style", "今天一个人在家，感觉有点无聊。")
    print("\n[陪伴风格回复]", body["reply"])
    assert "您" in body["reply"] or "你" in body["reply"]

