"""回忆录时间轴编排（M3）· 纯逻辑，不碰数据库。

把「已留档的故事」切成三组，**互斥且完备**（每条故事恰好落一组，各组之和 = 总数）：

| 组 | 命中条件 | UI 位置 |
|---|---|---|
| `era_axis`      | 有至少一个可归一的 `era_tags` | 主视图：横向时代带（色块） |
| `absolute_axis` | 无时代标签，但有绝对年份（自身 `time_value` 可解析，或由画像保守推断） | 副视图：绝对时间轴 |
| `unlocated`     | 两者都没有 | 单独一栏「还记得这些」 |

一条故事挂了多个时代时（如「知青年代」+「文革时期」），只归入**最早**的那一段，
卡片上仍带完整 `era_tags`——否则同一条故事会在时代带上出现两次，计数也对不上。

P4 降级（时间推算）：只用画像字段 `life_experience` / `family` 做**保守匹配**。
做法是「画像条目里要有年份 + 故事文本要与该条目共享足量词对」两道门，
命中才给 `time_inferred=True` 且 `time_confidence ≤ 0.5`，UI 显示「约」。

契约5（不纠正记忆偏差）：本模块**只读**。推断只存在于响应里，不回写数据库；
原文与 `time_value` 一律保持原样，偏差只在 `time_confidence` / 「约」字上体现。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Iterable, Optional, Sequence

from app.memoir import era_lexicon
from app.memoir.presenter import media_to_dict, story_to_dict
from app.schemas import StoryMediaItem, TimelineStory

logger = logging.getLogger(__name__)

# 推断时间的置信度上限（契约：推断值永远不能装成确定的）
INFERRED_CONFIDENCE_CAP = 0.5

_CN_DIGITS = {
    "〇": "0", "零": "0", "一": "1", "二": "2", "两": "2", "三": "3",
    "四": "4", "五": "5", "六": "6", "七": "7", "八": "8", "九": "9",
}
_ARABIC_YEAR = re.compile(r"(?<!\d)(1[89]\d{2}|20\d{2})(?!\d)")
_CN_YEAR = re.compile(r"[〇零一二三四五六七八九]{4}")
_ARABIC_DECADE = re.compile(r"(?<!\d)(\d{2})\s*年代?(?!\d)")
_CN_DECADE = re.compile(r"([一二三四五六七八九])\s*十\s*年代?")
_CJK = re.compile(r"[\u4e00-\u9fff]+")
# 画像条目里对「时间」无信息量的字，用于提纯锚词
_NOISE = re.compile(r"[年月日号的了是在有和跟到从又就都也很挺最把被让给对向于在]")


def parse_year(text: str) -> Optional[int]:
    """从口语/书面时间串里抠出一个年份；抠不出返回 None。

    覆盖：`1973年` / `1973年春天` / `一九七三年` / `二〇〇〇年` /
    `七十年代` / `上世纪80年代` / `两千年`。世纪敏感词（上世纪）会把
    两位数的年代强制锚到 19xx，避免把 `80年代` 误判成 2080。
    """
    if not text:
        return None
    raw = str(text)

    m = _ARABIC_YEAR.search(raw)
    if m:
        return int(m.group(1))

    m = _CN_YEAR.search(raw)
    if m:
        year = int("".join(_CN_DIGITS[c] for c in m.group(0)))
        if 1900 <= year <= 2100:
            return year

    if "两千年" in raw or "两千零" in raw:
        return 2000

    for_1900s = bool(re.search(r"上世纪|上个世纪|上一世纪", raw))
    m = _ARABIC_DECADE.search(raw)
    if m:
        n = int(m.group(1))
        base = 1900 if for_1900s or n >= 30 else 2000
        return base + n

    m = _CN_DECADE.search(raw)
    if m:
        decade = int(_CN_DIGITS[m.group(1)])
        return 1900 + decade * 10

    return None


def _bigrams(text: str) -> set[str]:
    """只取汉字、去掉年份与噪声字后的二元组集合（用于保守相似度比较）。"""
    if not text:
        return set()
    text = _ARABIC_YEAR.sub("", str(text))
    text = _CN_YEAR.sub("", text)
    text = _NOISE.sub("", text)
    chars = "".join(_CJK.findall(text))
    return {chars[i:i + 2] for i in range(len(chars) - 1)}


def infer_time_from_profile(
    story, entries: Sequence[str]
) -> Optional[tuple[int, float, str]]:
    """P4 降级：从画像经历条目里保守推测故事年份。

    两道门缺一不可：
    1. 画像条目本身含年份（否则无从推断）；
    2. 故事文本与该条目（去年份后）共享的二元词对达到阈值。

    返回 `(year, confidence, evidence)`；不命中返回 None。
    `confidence` 恒 ≤ INFERRED_CONFIDENCE_CAP。
    """
    story_text = f"{getattr(story, 'title', '') or ''} {getattr(story, 'summary', '') or ''}"
    story_grams = _bigrams(story_text)
    if not story_grams:
        return None

    best: Optional[tuple[int, float, str]] = None
    for entry in entries or ():
        year = parse_year(entry)
        if year is None:
            continue
        entry_grams = _bigrams(entry)
        if not entry_grams:
            continue
        overlap = len(story_grams & entry_grams)
        # 条目越短，可要求的重叠越少；但至少 1 个词对，且不超过条目本身长度
        needed = min(2, len(entry_grams))
        if overlap < needed:
            continue
        # 置信度随**共享词对数**单调递增（不是比例）：共享越多越可信，
        # 且短条目不会因为「分母小」而被高估。上限恒为 INFERRED_CONFIDENCE_CAP。
        confidence = round(min(INFERRED_CONFIDENCE_CAP, 0.30 + 0.10 * overlap), 3)
        candidate = (year, confidence, str(entry)[:60])
        # 命中更强则替换；强度相同取更早的年份（更贴近「早年经历」）
        if best is None or (confidence, -year) > (best[1], -best[0]):
            best = candidate

    return best


def _media_of(story, media_by_story: Optional[dict[int, Sequence]]) -> list[StoryMediaItem]:
    """取这条故事的照片（已按视角校验过可见性，这里只做转换）。"""
    if not media_by_story:
        return []
    rows = media_by_story.get(getattr(story, "id", None)) or ()
    owner = getattr(story, "elderly_user_id", "") or ""
    return [media_to_dict(m, owner) for m in rows]


def _timeline_story(
    story,
    *,
    display_time: str = "",
    inferred_from: str = "",
    era: str = "",
    media: Optional[list[StoryMediaItem]] = None,
) -> TimelineStory:
    base = story_to_dict(story, with_speech=False)
    data = base.model_dump()
    # media 由调用方按视角填（story_to_dict 里恒为空），避免重复传参
    data.pop("media", None)
    return TimelineStory(
        **data,
        display_time=display_time,
        inferred_from=inferred_from,
        era=era,
        media=list(media or []),
    )


def _era_display(era_meta: dict[str, Any]) -> str:
    start, end = era_meta.get("start_year"), era_meta.get("end_year")
    if start and end:
        return f"约{start}—{end}年"
    if start:
        return f"{start}年至今"
    return ""


def build_timeline(
    stories: Iterable,
    *,
    profile_entries: Sequence[str] = (),
    media_by_story: Optional[dict[int, Sequence]] = None,
) -> dict[str, Any]:
    """把 ORM 故事列表编排成三组时间轴。返回纯 dict（直接可序列化）。

    `media_by_story` 由服务层一次性查好（避免每条故事一次查询）；
    这里只负责挂到卡片上，**不做可见性判断**——那是调用方的职责。
    """
    era_groups: dict[str, list[TimelineStory]] = {}
    absolute: list[tuple[int, TimelineStory]] = []
    unlocated: list[TimelineStory] = []
    inferred_count = 0

    for story in stories:
        card_media = _media_of(story, media_by_story)
        canonical, _unmapped = era_lexicon.normalize_tags(getattr(story, "era_tags", None))
        if canonical:
            own_year = parse_year(getattr(story, "time_value", "") or "")
            # 一条故事可能同时挂多个时代（如「知青年代」+「文革时期」）。
            # 时间轴上一条故事只占一个位置——归到**最早**的那个时代段，
            # 完整 era_tags 仍留在卡片上，信息不丢。这样三组才是真互斥。
            primary = min(
                canonical,
                key=lambda n: (era_lexicon.era_meta(n) or {}).get("start_year") or 9999,
            )
            meta = era_lexicon.era_meta(primary) or {}
            display = f"{own_year}年" if own_year else _era_display(meta)
            era_groups.setdefault(primary, []).append(
                _timeline_story(
                    story, display_time=display, era=primary, media=card_media
                )
            )
            continue

        own_year = parse_year(getattr(story, "time_value", "") or "")
        if own_year is not None:
            absolute.append(
                (
                    own_year,
                    _timeline_story(
                        story, display_time=f"{own_year}年", media=card_media
                    ),
                )
            )
            continue

        hit = infer_time_from_profile(story, profile_entries) if profile_entries else None
        if hit is not None:
            year, confidence, evidence = hit
            meta = era_lexicon.era_of_year(year) or {}
            card = _timeline_story(
                story,
                display_time=f"约{year}年",
                inferred_from=evidence,
                era=meta.get("name", ""),
                media=card_media,
            )
            # 推断值不得装成确定值（契约5 的展示面）
            card.time_inferred = True
            card.time_confidence = min(
                confidence,
                INFERRED_CONFIDENCE_CAP,
                float(getattr(story, "time_confidence", 0.0) or 0.0) or INFERRED_CONFIDENCE_CAP,
            )
            inferred_count += 1
            absolute.append((year, card))
            continue

        unlocated.append(_timeline_story(story, media=card_media))

    # 时代轴：按年代排序；同段内按年份升序（未知年份沉底）
    era_axis: list[dict[str, Any]] = []
    for name, items in era_groups.items():
        meta = era_lexicon.era_meta(name) or {}
        items.sort(key=lambda s: (parse_year(s.display_time) or 9999, s.created_at))
        era_axis.append(
            {
                "era": name,
                "start_year": meta.get("start_year"),
                "end_year": meta.get("end_year"),
                "color": meta.get("color", ""),
                "count": len(items),
                "stories": items,
            }
        )
    era_axis.sort(key=lambda g: (g["start_year"] or 9999, g["era"]))

    absolute.sort(key=lambda pair: (pair[0], pair[1].created_at))
    absolute_axis = [item for _year, item in absolute]

    # 时间跨度：只用于 UI 画轴刻度，缺数据时为 None
    lo_candidates = [g["start_year"] for g in era_axis if g["start_year"]] + [
        y for y, _ in absolute
    ]
    hi_candidates = [y for y, _ in absolute] + [
        g["end_year"] or g["start_year"] for g in era_axis if g["start_year"]
    ]
    in_era = sum(g["count"] for g in era_axis)

    return {
        "era_axis": era_axis,
        "absolute_axis": absolute_axis,
        "unlocated": unlocated,
        "axis_span": {
            "min_year": min(lo_candidates) if lo_candidates else None,
            "max_year": max(hi_candidates) if hi_candidates else None,
        },
        "stats": {
            # 三组互斥，所以可以直接相加；等于去重后的故事条数
            "total": in_era + len(absolute_axis) + len(unlocated),
            "era_segments": len(era_axis),
            "in_era": in_era,
            "in_absolute": len(absolute_axis),
            "unlocated": len(unlocated),
            "inferred": inferred_count,
        },
    }
