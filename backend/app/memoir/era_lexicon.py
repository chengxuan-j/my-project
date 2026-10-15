"""时代词表加载与归一（D4 决策）。

`data/era_lexicon.json` 给出「规范时代名 + 同义词」。用途：
1. 提取 prompt 里列出规范名，让 LLM 只做「归一」而不是自由命名，避免标签漂移
   （否则同一段历史这月叫"知青岁月"、下月叫"上山下乡时期"，时代轴会碎）；
2. M3 时代轴按规范名分组、按 start_year 排序。

未命中任何规范名时返回 None，调用方决定是否标记 `unmapped`。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from app.config import BASE_DIR

logger = logging.getLogger(__name__)

LEXICON_PATH = Path(BASE_DIR) / "data" / "era_lexicon.json"

_cache: Optional[dict[str, Any]] = None
_synonym_index: dict[str, str] = {}


def load() -> dict[str, Any]:
    """读取词表（进程内缓存）。文件缺失/损坏时返回空结构，调用方需能降级。"""
    global _cache, _synonym_index
    if _cache is not None:
        return _cache

    try:
        with open(LEXICON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.error("读取 era_lexicon.json 失败，时代词表降级为空: %s", e)
        data = {"version": 0, "eras": []}

    index: dict[str, str] = {}
    for era in data.get("eras", []):
        name = era.get("name", "")
        if not name:
            continue
        index[name] = name
        for syn in era.get("synonyms", []):
            index[syn] = name

    _cache = data
    _synonym_index = index
    return data


def eras() -> list[dict[str, Any]]:
    return list(load().get("eras", []))


def canonical_names() -> list[str]:
    """规范时代名列表（按年代排序），供 prompt 与 UI 使用。"""
    items = eras()
    items.sort(key=lambda e: e.get("start_year") or 9999)
    return [e["name"] for e in items if e.get("name")]


def canonicalize(tag: str) -> Optional[str]:
    """把口语/同义标签归一到规范名；归不上返回 None。"""
    if not tag:
        return None
    load()
    tag = tag.strip()
    if tag in _synonym_index:
        return _synonym_index[tag]
    # 兜底：包含关系（"知青那几年" → "知青年代"）
    for syn, name in _synonym_index.items():
        if syn and (syn in tag or tag in syn):
            return name
    return None


def normalize_tags(tags: Any) -> tuple[list[str], list[str]]:
    """批量归一。返回 (规范标签去重列表, 未归一的原始标签列表)。"""
    canonical: list[str] = []
    unmapped: list[str] = []
    if not isinstance(tags, list):
        return canonical, unmapped
    for raw in tags:
        text = str(raw).strip()
        if not text:
            continue
        name = canonicalize(text)
        if name:
            if name not in canonical:
                canonical.append(name)
        elif text not in unmapped:
            unmapped.append(text)
    return canonical, unmapped


def era_meta(name: str) -> Optional[dict[str, Any]]:
    """规范名 → 时代元数据（含 start_year/end_year/color）。未知返回 None。"""
    for era in eras():
        if era.get("name") == name:
            return era
    return None


def era_of_year(year: int) -> Optional[dict[str, Any]]:
    """年份落在哪个时代区间内。多段重合时取**起点最晚**的那个（更具体）。

    例：1973 同时落在「知青年代(1968-1978)」与「票证年代(1955-1993)」，
    取知青年代——它对 1973 更有解释力。无命中返回 None。
    """
    hits = [
        e for e in eras()
        if isinstance(e.get("start_year"), int)
        and e["start_year"] <= year
        and (e.get("end_year") is None or year <= e["end_year"])
    ]
    if not hits:
        return None
    hits.sort(key=lambda e: (e["start_year"], -(e.get("end_year") or 9999)))
    return hits[-1]


def sorted_eras() -> list[dict[str, Any]]:
    """按 start_year 升序的规范时代列表（M3 时代轴排序基准）。"""
    items = eras()
    items.sort(key=lambda e: (e.get("start_year") or 9999, e.get("name") or ""))
    return items
