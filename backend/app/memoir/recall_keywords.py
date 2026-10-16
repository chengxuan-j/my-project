"""回忆类关键词快筛（实时回忆模式，2026-10-15）。

设计意图：老人**一聊到往事**就记档并推给家属，不等完整度攒够。
触发条件简化为「消息命中回忆类关键词」——命中才花一次 LLM 调用
判断是不是生平故事，不命中直接跳过（零成本、零打扰）。

词表两部分：
1. 通用回忆口语（以前/当年/想起……）；
2. `data/era_lexicon.json` 的时代同义词（知青/粮票/下岗……）——
   复用已有词表，不另维护一套。

少数太泛的词（"现在""这几年"）日常聊天高频，命中会把闲聊也送进 LLM，
单独排除。LLM 的 is_life_story 判定是第二道闸，错命中只是费一次调用。
"""
from __future__ import annotations

import logging

from app.memoir import era_lexicon

logger = logging.getLogger(__name__)

# 通用回忆口语（子串匹配，短词优先）
RECALL_WORDS: tuple[str, ...] = (
    "以前", "从前", "当年", "想当年", "早年", "小时候", "那会儿", "那时候",
    "那阵子", "想起", "回忆", "还记得", "想当初", "往事", "曾经", "过去",
    "老早", "老家", "老单位", "故事", "一辈子", "年轻那会儿", "年轻时",
)

# 时代词表里太泛、会误触发的同义词，不进关键词
_TOO_GENERIC = {"现在", "这几年", "最近这些年"}


def _era_words() -> list[str]:
    words: list[str] = []
    try:
        for era in era_lexicon.eras():
            for syn in era.get("synonyms", []):
                syn = str(syn).strip()
                if syn and syn not in _TOO_GENERIC:
                    words.append(syn)
            name = str(era.get("name", "")).strip()
            if name and name not in _TOO_GENERIC:
                words.append(name)
    except Exception as e:  # noqa: BLE001  词表挂了不影响通用词
        logger.warning("时代词表加载失败，回忆关键词仅用通用词: %s", e)
    return words


_KEYWORDS: tuple[str, ...] = tuple(dict.fromkeys(list(RECALL_WORDS) + _era_words()))


def matched_word(text: str) -> str:
    """返回消息中命中的回忆关键词（取最长命中，日志更可读）；未命中返回 ""。"""
    if not text:
        return ""
    hits = [w for w in _KEYWORDS if w in text]
    return max(hits, key=len) if hits else ""
