"""生平故事提取器（独立于事实记忆管线）。

- 只做「这一轮对话里有没有值得留档的往事」判断，返回结构化 dict；
- **不碰数据库**：落库由 M1 的 story_repo / story_service 负责，保持与
  `MemoryExtractor`（只 LLM）+ `MemoryStore`（只落库）相同的分工；
- LLM 不可用 / 解析失败 → 返回 None（静默降级，绝不阻塞 /chat）。
"""
import logging
from typing import Any, Optional

from app.core.json_utils import parse_json_loose
from app.llm.qwen_client import LLMError, QwenClient
from app.memoir import era_lexicon
from app.memoir.prompts import EMOTION_TONES, EXTRACT_SYSTEM_PROMPT, TIME_TYPES

logger = logging.getLogger(__name__)

MAX_TITLE_LEN = 20
MAX_SUMMARY_LEN = 80


def _clamp01(value: Any, default: float = 0.5) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in out:
            out.append(text)
    return out


def _clip(text: Any, limit: int) -> str:
    return str(text or "").strip()[:limit]


class StoryExtractor:
    """用一次独立的轻量 Qwen 调用判断本轮是否包含生平往事。"""

    def __init__(self, client: Optional[QwenClient] = None) -> None:
        self.client = client or QwenClient()

    @property
    def is_configured(self) -> bool:
        return bool(getattr(self.client, "is_configured", False))

    async def extract(self, user_message: str, ai_reply: str = "") -> Optional[dict]:
        """返回归一化后的故事 dict；不是故事 / 调不通 / 解析失败一律返回 None。"""
        result, _raw, _err = await self.extract_debug(user_message, ai_reply)
        return result

    async def extract_debug(
        self, user_message: str, ai_reply: str = ""
    ) -> tuple[Optional[dict], str, Optional[str]]:
        """带调试信息的版本：返回 (归一化结果, LLM 原文, 错误信息)。

        供 M0 的 extract_stories_probe.py 使用，便于人工复盘 prompt 哪里判错了。
        """
        messages = [
            {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
            {"role": "user", "content": f"老人说：{user_message}\n助手回复：{ai_reply}"},
        ]
        try:
            raw = await self.client.chat(messages, temperature=0.0, max_tokens=400)
        except LLMError as e:
            logger.warning("生平故事提取调用失败，跳过本轮: %s", e)
            return None, "", str(e)

        data = parse_json_loose(raw)
        if data is None:
            logger.warning("生平故事提取返回非 JSON，已跳过。原文前 120 字：%s", raw[:120])
            return None, raw, "non_json"

        if isinstance(data, list):
            data = data[0] if data else None
        if not isinstance(data, dict) or not data.get("is_life_story"):
            return None, raw, None

        return _normalize(data), raw, None


def _normalize(data: dict) -> dict:
    """字段归一 + 取值约束，保证下游（落库/编排）拿到的一定是干净结构。"""
    time_raw = data.get("time") if isinstance(data.get("time"), dict) else {}
    time_type = str(time_raw.get("type", "relative")).strip()
    if time_type not in TIME_TYPES:
        time_type = "relative"

    era_tags, unmapped = era_lexicon.normalize_tags(data.get("era_tags"))

    tone = str(data.get("emotion_tone", "")).strip()
    if tone not in EMOTION_TONES:
        tone = "平淡"

    return {
        "is_life_story": True,
        "confidence": _clamp01(data.get("confidence"), 0.6),
        "title": _clip(data.get("title"), MAX_TITLE_LEN),
        "summary": _clip(data.get("summary"), MAX_SUMMARY_LEN),
        "time": {
            "type": time_type,
            "value": _clip(time_raw.get("value"), 40),
            "confidence": _clamp01(time_raw.get("confidence"), 0.3),
        },
        "era_tags": era_tags,
        # 未归一到词表的原始标签，留作 M3 排查"哪些口语锚点还没进词表"
        "era_tags_unmapped": unmapped,
        "place": _clip(data.get("place"), 40),
        "people": _as_str_list(data.get("people")),
        "emotion_tone": tone,
        "missing": _as_str_list(data.get("missing")),
        "follow_up_hint": _clip(data.get("follow_up_hint"), 80),
    }
