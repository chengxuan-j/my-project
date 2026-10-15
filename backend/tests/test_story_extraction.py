"""生平故事提取（M0/M1）单测。

不依赖真实 Qwen Key：用 FakeClient 注入受控的 LLM 返回，覆盖
「归一化 / 时代标签归一 / 非法值收敛 / 各类失败静默降级」四条主线。

无 Key 时也能跑：`python -m pytest tests/test_story_extraction.py -v`
"""
import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pytest

from app.core.json_utils import parse_json_loose
from app.llm.qwen_client import LLMError
from app.memoir import era_lexicon
from app.memoir.story_extractor import StoryExtractor


class FakeClient:
    """受控 LLM：要么返回固定文本，要么抛指定异常。"""

    def __init__(self, response: str = "", error: Exception | None = None,
                 configured: bool = True) -> None:
        self.model = "fake-model"
        self.is_configured = configured
        self._response = response
        self._error = error

    async def chat(self, messages, **kwargs) -> str:  # noqa: ANN001
        if self._error is not None:
            raise self._error
        return self._response


def _extractor(response: str = "", **kw) -> StoryExtractor:
    return StoryExtractor(FakeClient(response=response, **kw))


# ---------------------------------------------------------------------------
# 时代词表（D4）
# ---------------------------------------------------------------------------

def test_era_lexicon_canonicalize():
    assert era_lexicon.canonicalize("上山下乡") == "知青年代"
    assert era_lexicon.canonicalize("知青那几年") == "知青年代"  # 包含关系兜底
    assert era_lexicon.canonicalize("粮票") == "票证年代"
    assert era_lexicon.canonicalize("完全不存在的说法") is None


def test_era_lexicon_normalize_tags():
    canonical, unmapped = era_lexicon.normalize_tags(["知青", "粮票", "自创时代"])
    assert canonical == ["知青年代", "票证年代"]
    assert unmapped == ["自创时代"]


# ---------------------------------------------------------------------------
# 宽松 JSON 解析
# ---------------------------------------------------------------------------

def test_parse_json_loose_strips_fence():
    assert parse_json_loose('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_loose('好的，结果是{"a": 2}') == {"a": 2}
    assert parse_json_loose("完全不是 JSON") is None


# ---------------------------------------------------------------------------
# 提取：正常路径
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_returns_normalized_story():
    raw = json.dumps({
        "is_life_story": True,
        "confidence": 0.85,
        "title": "纺织厂的第一天",
        "summary": "十八岁进纺织厂，第一次听见车间机器的轰鸣。",
        "time": {"type": "era_anchor", "value": "刚进厂那会儿", "confidence": 0.6},
        "era_tags": ["知青"],
        "place": "纺织厂车间",
        "people": ["老师傅（带她的师傅）"],
        "emotion_tone": "怀念",
        "missing": ["具体年份"],
        "follow_up_hint": "可以问问她第一天进车间时紧不紧张",
    }, ensure_ascii=False)

    story = await _extractor(raw).extract("我十八岁进厂，机器响得吓人。", "那可真吵。")

    assert story is not None
    assert story["is_life_story"] is True
    assert story["title"] == "纺织厂的第一天"
    assert story["emotion_tone"] == "怀念"
    assert story["time"]["type"] == "era_anchor"
    assert story["people"] == ["老师傅（带她的师傅）"]
    assert story["missing"] == ["具体年份"]


@pytest.mark.asyncio
async def test_extract_canonicalizes_era_tags():
    raw = json.dumps({
        "is_life_story": True, "title": "下乡", "summary": "去黑龙江。",
        "era_tags": ["上山下乡", "粮票", "我家那旮旯"],
    }, ensure_ascii=False)

    story = await _extractor(raw).extract("我十六岁下乡去了黑龙江。", "")

    assert story is not None
    assert story["era_tags"] == ["知青年代", "票证年代"]        # 归一成功
    assert story["era_tags_unmapped"] == ["我家那旮旯"]          # 未命中单独留存


@pytest.mark.asyncio
async def test_extract_clamps_invalid_values():
    raw = json.dumps({
        "is_life_story": True, "confidence": 3.7,
        "title": "x" * 100, "summary": "y" * 200,
        "time": {"type": "不存在的类型", "value": "z" * 100, "confidence": -5},
        "emotion_tone": "莫名其妙",
    }, ensure_ascii=False)

    story = await _extractor(raw).extract("往事。", "")

    assert story is not None
    assert story["confidence"] == 1.0                  # 上界收敛
    assert story["time"]["confidence"] == 0.0          # 下界收敛
    assert story["time"]["type"] == "relative"         # 非法类型回落
    assert story["emotion_tone"] == "平淡"              # 非法情绪回落
    assert len(story["title"]) <= 20                   # 截断
    assert len(story["summary"]) <= 80


# ---------------------------------------------------------------------------
# 提取：降级路径（不得抛错）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_returns_none_when_not_story():
    story = await _extractor(json.dumps({"is_life_story": False})).extract("今天天气不错。", "")
    assert story is None


@pytest.mark.asyncio
async def test_extract_returns_none_on_non_json():
    story, raw, error = await _extractor("我觉得是的，但没有 JSON").extract_debug("往事", "")
    assert story is None
    assert error == "non_json"
    assert raw  # 原文被保留，便于复盘


@pytest.mark.asyncio
async def test_extract_returns_none_on_llm_error():
    ex = _extractor(error=LLMError("网络错误"))
    story, _raw, error = await ex.extract_debug("往事", "")
    assert story is None
    assert error and "网络错误" in error


@pytest.mark.asyncio
async def test_extract_without_key_does_not_raise():
    """无 Key（未配置）时静默跳过，不抛异常——全链路无 Key 不阻塞 /chat。"""
    ex = _extractor(error=LLMError("未配置 QWEN_API_KEY"), configured=False)
    assert ex.is_configured is False
    assert await ex.extract("我年轻时候在纺织厂。", "") is None
