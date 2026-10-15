"""M5 故事板编排器（契约6：只到提示词，不生成任何画面）。

输入一批**已留档（archived）**的故事 → 排成一条 60 秒左右的故事板 →
输出结构化 `prompt_package`，状态止于 `prompt_ready`。

分工刻意做成"代码管骨架、LLM 管血肉"：

| 谁 | 管什么 | 为什么 |
|---|---|---|
| 代码 | 选定哪些故事、按时代轴排序、每段多长、总时长 | 要可控可测，不能交给模型 |
| LLM  | 旁白怎么讲、画面怎么写 | 这是一次创作，但必须落在代码给的框子里 |

**时长由代码分配、不采信 LLM**：模型给的秒数加起来永远不等于 60，
而且这次多 3 秒、下次少 5 秒，前端进度条就没法对齐。

四条后校验（LLM 输出一律视为不可信输入）：

1. `narration` 必须第一人称、且与老人原话足够接近，否则回退用原句（契约4）；
2. `visual_prompt` 里出现人脸类词 → **逐短语剔除**，剔空则用安全兜底（契约6 延伸）；
3. `disclaimer` 缺失 → 强制补默认文案，不允许没有免责声明；
4. `source_evidence` 一律用代码写入的老人原话，不采信模型（免得编造出处）。

降级：LLM 不可用 → 按时代轴线性拼接，`narration` 用老人原话/`summary`，
`visual_prompt` 留空（前端显示占位色块），`status` 仍是 `prompt_ready`。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional, Sequence

from app.core.json_utils import parse_json_loose
from app.llm.qwen_client import LLMError, QwenClient
from app.memoir import era_lexicon
from app.memoir.prompts import STORYBOARD_SYSTEM_PROMPT
from app.memoir.timeline import parse_year

logger = logging.getLogger(__name__)

DEFAULT_TOTAL_SECONDS = 60
MIN_SCENE_SECONDS = 4
MAX_SCENE_SECONDS = 25
MAX_SCENES = 12

NARRATION_MAX_LEN = 45
VISUAL_MAX_LEN = 60

# 旁白与原话的最低相似度：低于它说明模型改写了事实，回退用原句（契约4）
NARRATION_MIN_SIMILARITY = 0.30

# 第三人称指代：模型把主角写成了"她/他/老人"，就是违约（契约4）。
# 不说"必须含『我』"——中文主语省略是常态，"那时候买米买面都得要粮票"
# 本来就是老人自己的原话，硬要求含"我"会误杀一大片合格旁白。
THIRD_PERSON_MARKERS = ("她", "他", "老人", "老人家", "阿姨", "奶奶", "爷爷", "大伯", "大妈")

# 人脸类词：命中即剔除所在短语（契约6 延伸——不描述具体人脸）
FACE_BAN_WORDS = (
    "脸", "面部", "面孔", "五官", "相貌", "长相", "肖像", "容貌",
    "特写", "portrait", "face", "close-up", "close up", "headshot",
)

# 免责声明：后校验发现缺失就补这句，不允许没有
DEFAULT_DISCLAIMER = (
    "本片由老人讲述的回忆整理而成，画面为示意；时间与细节以老人本人说法为准。"
)

# 画面兜底（不含人脸，只写环境）
VISUAL_FALLBACK = "年代感的生活环境空镜，柔和自然光，暖黄色调，胶片质感，远景"

_PHRASE_SPLIT = re.compile(r"[，,。；;、\n]+")


# ---------------------------------------------------------------------------
# 纯函数：排序 / 时长 / 后校验
# ---------------------------------------------------------------------------

def story_sort_key(story) -> tuple:
    """时代轴排序键：先按最早时代的起始年，再按故事自身的年份，最后按 id。

    与 M3 时代轴口径一致——故事板让老人看到的时间顺序，必须和他自己
    在回忆录里看到的一致，否则同一件事在两处顺序不同，很困惑。
    """
    canonical, _ = era_lexicon.normalize_tags(getattr(story, "era_tags", None))
    era_start = 9999
    for name in canonical:
        meta = era_lexicon.era_meta(name) or {}
        start = meta.get("start_year") or 9999
        era_start = min(era_start, start)
    year = parse_year(getattr(story, "time_value", "") or "") or 9999
    return (era_start, year, getattr(story, "id", 0) or 0)


def original_quote(story) -> str:
    """老人在这个话题上说过的话（第一人称原话），没有就用 summary。"""
    for turn in (getattr(story, "raw_dialogue", None) or []):
        if isinstance(turn, dict) and turn.get("role") == "user":
            text = str(turn.get("content") or "").strip()
            if text:
                return text
    return str(getattr(story, "summary", "") or "").strip()


def allocate_durations(count: int, total_seconds: int = DEFAULT_TOTAL_SECONDS) -> list[int]:
    """把总时长平均分给每段，并夹在 [MIN, MAX] 之间。

    整数平均，余数补给前几段，保证 **各段之和恰好等于总时长**
    （除非段数太多导致每段都顶到下限——那时总长会超，是真实的取舍，
    调用方从 `planned_total` 能看到实际值）。
    """
    if count <= 0:
        return []
    per = min(MAX_SCENE_SECONDS, max(MIN_SCENE_SECONDS, total_seconds // count))
    durations = [per] * count
    remainder = total_seconds - per * count
    i = 0
    while remainder > 0 and per < MAX_SCENE_SECONDS:
        durations[i % count] += 1
        remainder -= 1
        i += 1
    return durations


def _bigrams(text: str) -> set[str]:
    chars = re.sub(r"[^\u4e00-\u9fff]", "", text or "")
    return {chars[i:i + 2] for i in range(len(chars) - 1)}


def similarity(a: str, b: str) -> float:
    """字符 bigram 覆盖率（0~1）。用覆盖率而非 Jaccard：原话更长时不该被罚。"""
    ab, bb = _bigrams(a), _bigrams(b)
    if not ab or not bb:
        return 0.0
    return len(ab & bb) / len(ab)


def sanitize_visual_prompt(text: str, fallback: str = VISUAL_FALLBACK) -> str:
    """剔除含人脸类词的短语；剔空则用兜底。

    逐短语剔除而不是整条丢弃：模型常常只在一处顺手写了"脸上带着笑"，
    整条扔掉会白费掉其余很好的场景描述。判定必须在**短语内部**做，
    否则一个短语命中就会把整条画面描述清空。
    """
    raw = str(text or "").strip()
    if not raw:
        return fallback
    kept: list[str] = []
    for phrase in _PHRASE_SPLIT.split(raw):
        phrase = phrase.strip()
        if not phrase:
            continue
        lowered = phrase.lower()
        if any(word in lowered for word in FACE_BAN_WORDS):
            continue
        kept.append(phrase)
    result = "，".join(kept)[:VISUAL_MAX_LEN].strip("，")
    return result or fallback


def introduces_third_person(text: str, original: str) -> bool:
    """模型是否把老人改写成了第三人称。

    只在「老人原话里本来没有这个指代词」时才算违约——原话里说
    「跟他是在厂里认识的」，那个"他"指的是老伴，模型照用没问题。
    """
    return any(m in text and m not in original for m in THIRD_PERSON_MARKERS)


def pick_narration(candidate: str, original: str) -> tuple[str, str]:
    """选定旁白。返回 `(旁白, 来源)`，来源 ∈ {original, model, summary}。

    契约4「优先老人原话」在这里落地：模型把老人写成了第三人称、
    或者改写幅度过大（相似度低于阈值），就退回老人原话——
    宁可粗糙，不能失真。
    """
    original = (original or "").strip()
    text = str(candidate or "").strip()

    if not text:
        return (original or "")[:NARRATION_MAX_LEN], "original" if original else "summary"

    drifted = bool(original) and introduces_third_person(text, original)
    too_far = bool(original) and similarity(text, original) < NARRATION_MIN_SIMILARITY
    if drifted or too_far:
        if original:
            return original[:NARRATION_MAX_LEN], "original"
        return text[:NARRATION_MAX_LEN], "model"
    return text[:NARRATION_MAX_LEN], "model"


def build_scene_plan(stories: Sequence, total_seconds: int = DEFAULT_TOTAL_SECONDS) -> list[dict]:
    """纯函数：选出故事、排好序、分好时长。这是交由 LLM 展开的骨架。"""
    ordered = sorted(stories, key=story_sort_key)[:MAX_SCENES]
    durations = allocate_durations(len(ordered), total_seconds)
    plan: list[dict] = []
    for story, seconds in zip(ordered, durations):
        canonical, _ = era_lexicon.normalize_tags(getattr(story, "era_tags", None))
        plan.append({
            "story_id": getattr(story, "id", 0),
            "era": canonical[0] if canonical else "",
            "title": getattr(story, "title", "") or "",
            "display_time": (
                str(getattr(story, "time_value", "") or "")
                or (canonical[0] if canonical else "")
            ),
            "original": original_quote(story),
            "summary": getattr(story, "summary", "") or "",
            "place": getattr(story, "place", "") or "",
            "emotion_tone": getattr(story, "emotion_tone", "") or "",
            "duration_seconds": seconds,
        })
    return plan


# ---------------------------------------------------------------------------
# 后校验：把 LLM 输出塞进骨架（LLM 输出视为不可信输入）
# ---------------------------------------------------------------------------

def assemble_package(
    data: Optional[dict],
    plan: list[dict],
    *,
    perspective: str = "first_person",
    llm_used: bool = False,
    requested_seconds: int = DEFAULT_TOTAL_SECONDS,
) -> dict:
    """把（可能没有、可能残缺的）LLM 输出与代码骨架合成为最终提示词包。"""
    data = data if isinstance(data, dict) else {}
    raw_scenes = data.get("scenes") if isinstance(data.get("scenes"), list) else []

    # 按 story_id 对齐；对不上就按位置兜底，绝不因为模型乱序就丢段
    by_id: dict[Any, dict] = {}
    for item in raw_scenes:
        if isinstance(item, dict) and item.get("story_id") is not None:
            by_id.setdefault(item["story_id"], item)

    scenes: list[dict] = []
    for index, item in enumerate(plan):
        raw = by_id.get(item["story_id"])
        if raw is None and index < len(raw_scenes) and isinstance(raw_scenes[index], dict):
            raw = raw_scenes[index]
        raw = raw or {}

        narration, source = pick_narration(raw.get("narration", ""), item["original"])
        scenes.append({
            "index": index + 1,
            "story_id": item["story_id"],
            "era": item["era"],
            "title": item["title"],
            "display_time": item["display_time"],
            "place": item["place"],
            "emotion_tone": item["emotion_tone"],
            # 代码分配，不采信 LLM
            "duration_seconds": item["duration_seconds"],
            "narration": narration,
            # "original" 表示这句是老人原话，UI 可以标出来
            "narration_source": source,
            "visual_prompt": sanitize_visual_prompt(raw.get("visual_prompt", "")),
            # 出处由代码写死，不采信模型（免得编造来源）
            "source_evidence": item["original"] or item["summary"],
        })

    total = sum(s["duration_seconds"] for s in scenes)
    title = str(data.get("title") or "").strip()[:24]
    if not title:
        title = plan[0]["title"] if plan else "我的一段日子"
    pkg_perspective = str(data.get("perspective") or "").strip()
    if pkg_perspective not in ("first_person", "third_person"):
        pkg_perspective = perspective

    return {
        "title": title,
        "perspective": pkg_perspective,
        "total_seconds": total,
        # 段数太少时会顶到 MAX_SCENE_SECONDS，实际总长可能短于请求值。
        # 两个数都留着，前端能如实显示，不假装凑够了 60 秒。
        "requested_seconds": requested_seconds,
        # 强制存在：缺失就补默认，不允许没有免责声明
        "disclaimer": str(data.get("disclaimer") or "").strip() or DEFAULT_DISCLAIMER,
        "scenes": scenes,
        "render_engine": None,          # 契约6：不接任何生成服务
        "llm_used": llm_used,
    }


# ---------------------------------------------------------------------------
# 编排器
# ---------------------------------------------------------------------------

class StoryboardBuilder:
    """一次 LLM 调用产出整个 prompt_package；不可用时线性降级。"""

    def __init__(self, client: Optional[QwenClient] = None) -> None:
        self.client = client or QwenClient()

    @property
    def is_configured(self) -> bool:
        return bool(getattr(self.client, "is_configured", False))

    def _user_message(self, plan: list[dict]) -> str:
        blocks = []
        for i, item in enumerate(plan, 1):
            blocks.append(
                f"【第 {i} 段】story_id={item['story_id']}"
                f"\n时代：{item['era'] or '未定位'}｜时间：{item['display_time'] or '不详'}"
                f"｜地点：{item['place'] or '不详'}｜情绪：{item['emotion_tone'] or '平淡'}"
                f"\n标题：{item['title'] or '（无）'}"
                f"\n老人原话：{item['original'] or item['summary'] or '（无）'}"
            )
        return (
            f"共 {len(plan)} 段，请为每段写旁白与画面，并按顺序输出 scenes。\n\n"
            + "\n\n".join(blocks)
        )

    async def build(
        self, stories: Sequence, *, total_seconds: int = DEFAULT_TOTAL_SECONDS
    ) -> dict:
        """编排成 prompt_package。空输入返回空包（不抛错）。"""
        plan = build_scene_plan(stories, total_seconds)
        if not plan:
            return assemble_package(None, [], llm_used=False,
                                    requested_seconds=total_seconds)

        messages = [
            {"role": "system", "content": STORYBOARD_SYSTEM_PROMPT},
            {"role": "user", "content": self._user_message(plan)},
        ]
        try:
            raw = await self.client.chat(messages, temperature=0.7, max_tokens=1600)
        except LLMError as e:
            logger.warning("故事板编排调用失败，走线性降级: %s", e)
            return assemble_package(None, plan, llm_used=False,
                                    requested_seconds=total_seconds)

        data = parse_json_loose(raw)
        if data is None:
            logger.warning("故事板返回非 JSON，走线性降级。原文前 120 字：%s", raw[:120])
            return assemble_package(None, plan, llm_used=False,
                                    requested_seconds=total_seconds)

        if isinstance(data, list):
            data = data[0] if data else None
        if not isinstance(data, dict):
            return assemble_package(None, plan, llm_used=False,
                                    requested_seconds=total_seconds)

        package = assemble_package(data, plan, llm_used=True,
                                   requested_seconds=total_seconds)
        banned = sum(
            1 for s in package["scenes"]
            if s["visual_prompt"] == VISUAL_FALLBACK
        )
        if banned:
            logger.info("故事板：%d 段画面提示因含人脸描述被剔除并兜底", banned)
        return package
