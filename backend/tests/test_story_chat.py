"""对话式引导（story_chat）的单元测试。

关注的不是"模型问得好不好"，而是三条底线：
1. 任何情况下都能接上下一句（模型挂了也有规则句）；
2. 要往前推故事（不再围着同一个细节打转），有情绪时先共情；
3. 不设轮次上限，永远不自动收尾。
"""
import pytest

from app.llm.qwen_client import LLMError
from app.memoir import story_chat


class _FailClient:
    analysis_model = "qwen-flash"

    async def chat(self, *args, **kwargs):
        raise LLMError("模型不可用")


class _StubClient:
    analysis_model = "qwen-flash"

    def __init__(self, payload: str):
        self.payload = payload

    async def chat(self, *args, **kwargs):
        return self.payload


@pytest.mark.asyncio
async def test_llm_reply_is_used_when_valid():
    turns = [{"role": "user", "content": "我十七岁那年去修水库，天没亮就出发。"}]
    payload = '{"reply": "水库在哪个县？", "move": "detail", "focus": "place"}'
    r = await story_chat.next_reply(turns, client=_StubClient(payload))
    assert r["source"] == "llm"
    assert r["question"] == "水库在哪个县？"
    assert r["done"] is False


@pytest.mark.asyncio
async def test_llm_down_pushes_story_forward():
    """模型挂掉时，第一句要往前推，而不是继续抠细节。"""
    turns = [{"role": "user", "content": "我十七岁那年去修水库，天没亮就出发。"}]
    r = await story_chat.next_reply(turns, client=_FailClient())
    assert r["source"] == "rule"
    assert r["question"].endswith("？")
    assert r["focus"] == "progress"
    assert "后来" in r["question"] or "往后" in r["question"]


@pytest.mark.asyncio
async def test_rule_reply_never_uses_template_empathy():
    """规则兜底不套「听着就……」这种模板，只把话往下推。"""
    turns = [{"role": "user", "content": "工地上住席棚，冬天冷得睡不着。"}]
    r = await story_chat.next_reply(turns, client=_FailClient())
    assert not any(w in r["question"] for w in story_chat.BANNED_CLICHES)
    assert r["question"].endswith("？")


@pytest.mark.asyncio
async def test_cliche_prefix_is_stripped():
    """模型非要说「听着就冷。后来呢？」，就只留后半句问话。"""
    turns = [{"role": "user", "content": "冬天冷得睡不着。"}]
    payload = '{"reply": "听着就冷。后来呢？", "focus": "progress"}'
    r = await story_chat.next_reply(turns, client=_StubClient(payload))
    assert r["question"] == "后来呢？"
    assert "听着就" not in r["question"]


@pytest.mark.asyncio
async def test_rule_reply_turns_away_when_elder_avoids():
    turns = [{"role": "user", "content": "这段我不记得了。"}]
    r = await story_chat.next_reply(turns, client=_FailClient())
    assert r["question"] == story_chat.AVOID_REPLY


@pytest.mark.asyncio
async def test_rule_reply_is_gentle_on_heavy_topic():
    """有人离世时不能催"后来又出了什么事"。"""
    turns = [{"role": "user", "content": "前年他儿子来电话，说老王走了。"}]
    r = await story_chat.next_reply(turns, client=_FailClient())
    assert r["question"] in story_chat.HEAVY_REPLIES
    assert "又出了什么事" not in r["question"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        "后来呢",  # 没有问号
        '{"reply": "后来呢？", "focus": "progress", "x":}',  # 坏 JSON
        '{"reply": "' + "您" * 60 + '？", "focus": "progress"}',  # 太长
        '{"reply": "", "focus": "progress"}',  # 空
        '{"reply": "那真够早的？", "focus": "time"}',  # 陈述句硬加问号
    ],
)
async def test_bad_llm_output_falls_back(payload):
    turns = [{"role": "user", "content": "我十七岁那年去修水库。"}]
    r = await story_chat.next_reply(turns, client=_StubClient(payload))
    assert r["source"] == "rule"


@pytest.mark.asyncio
async def test_duplicate_reply_is_rejected():
    turns = [
        {"role": "user", "content": "我十七岁那年去修水库。"},
        {"role": "assistant", "content": "后来呢？"},
    ]
    payload = '{"reply": "后来呢？", "focus": "progress"}'
    r = await story_chat.next_reply(turns, client=_StubClient(payload))
    assert r["question"] != "后来呢？"


@pytest.mark.asyncio
async def test_rule_replies_never_repeat_and_keep_going():
    """连续 6 轮（模型全程不可用）：不重复、也不出现收尾话。"""
    turns: list[dict] = [{"role": "user", "content": "那年冬天很冷。"}]
    seen: list[str] = []
    for _ in range(6):
        r = await story_chat.next_reply(turns, client=_FailClient())
        assert r["done"] is False
        assert "这段我记下了" not in r["question"]
        assert r["question"] not in seen
        seen.append(r["question"])
        turns.append({"role": "assistant", "content": r["question"]})
        turns.append({"role": "user", "content": "嗯，接着说吧。"})


@pytest.mark.asyncio
async def test_no_closing_even_after_many_rounds():
    """没有轮次上限：问满 10 轮之后仍是正常追问。"""
    turns: list[dict] = []
    for i in range(10):
        turns.append({"role": "user", "content": f"第 {i} 段往事。"})
        turns.append({"role": "assistant", "content": f"第 {i} 个问题？"})
    r = await story_chat.next_reply(turns, client=_StubClient("{}"))
    assert r["done"] is False
    assert r["question"].endswith("？")
    assert "保存" not in r["question"]
