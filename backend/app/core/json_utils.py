"""宽松 JSON 解析（LLM 输出容错）。

LLM 经常把 JSON 包在 markdown 代码围栏里，或在前后加一句解释。
本模块提供统一的抽取逻辑，供回忆录提取/编排等模块复用。

说明：`app/memory/memory_extractor.py` 里有一份等价实现，但按回忆录开发计划
「memory/ 不动」的约束，这里独立提供一份，不改动既有事实记忆管线。
"""
import json
import re
from typing import Any, Optional

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
_JSON_RE = re.compile(r"\{.*\}|\[.*\]", re.S)


def parse_json_loose(text: str) -> Optional[Any]:
    """从 LLM 原始输出里尽量抽出一个 JSON 对象/数组；失败返回 None。"""
    if not text:
        return None

    candidates = []
    stripped = text.strip()
    candidates.append(stripped)
    # 优先取代码围栏内容
    for m in _FENCE_RE.finditer(text):
        candidates.append(m.group(1).strip())
    candidates.append(re.sub(r"^json\s*", "", stripped, flags=re.I))

    for cand in candidates:
        try:
            return json.loads(cand)
        except (json.JSONDecodeError, TypeError):
            pass

    # 最后兜底：抓第一个大括号/中括号块
    m = _JSON_RE.search(text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None
