"""缺口检测：把提取结果里的 missing 转成可追问的队列条目。

职责边界：**只做检测与排队，不做时机决策**。什么时候问、要不要问由 M4 的
elicitation.py 决定（那里有 risk_level / cooldown / 单次会话硬上限三道门禁）。

为什么优先级要区分类型：时代轴（M3 主视图）完全依赖时间信息，所以
missing_time 的追问价值最高；细节缺口最廉价。
"""
from typing import Any

# 缺口类型 → 关键词（用于把 missing 的自然语言描述归类）
_TIME_WORDS = ("年", "时间", "哪一年", "什么时候", "年代", "几岁", "多大", "日子")
_PLACE_WORDS = ("地点", "哪儿", "哪里", "地方", "在什么地", "厂区", "村子", "城市")
_PERSON_WORDS = ("人", "谁", "名字", "全名", "叫什么", "关系", "同伴", "家人", "工友")

# 类型 → 基础优先级（时间最值钱，细节最廉价）
_BASE_PRIORITY = {
    "missing_time": 0.8,
    "missing_person": 0.7,
    "missing_place": 0.65,
    "missing_detail": 0.5,
}

# 每条故事最多排几个追问（契约3：克制，不要堆给老人一堆问题）
MAX_GAPS_PER_STORY = 3


def classify_gap(missing_text: str) -> str:
    """把 missing 的自然语言描述归类到四种 gap_type。"""
    text = str(missing_text or "")
    if any(w in text for w in _TIME_WORDS):
        return "missing_time"
    if any(w in text for w in _PLACE_WORDS):
        return "missing_place"
    if any(w in text for w in _PERSON_WORDS):
        return "missing_person"
    return "missing_detail"


def detect_gaps(extraction: dict[str, Any]) -> list[dict[str, Any]]:
    """从提取结果推出缺口列表，按优先级降序，最多 MAX_GAPS_PER_STORY 条。

    返回元素：{"gap_type", "question", "priority"}
    question 只是"追问方向"，M4 会交给主模型改写成自然问句，不直接念模板。
    """
    missing = extraction.get("missing") or []
    if not isinstance(missing, list):
        return []

    confidence = float(extraction.get("confidence") or 0.5)
    hint = str(extraction.get("follow_up_hint") or "").strip()

    gaps: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in missing:
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        gap_type = classify_gap(text)
        # 故事本身越确定，追问越值得；缺口描述越具体，追问越容易问出口
        priority = _BASE_PRIORITY[gap_type] * (0.6 + 0.4 * confidence)
        gaps.append({
            "gap_type": gap_type,
            "question": text[:200],
            "priority": round(min(1.0, priority), 3),
        })

    gaps.sort(key=lambda g: g["priority"], reverse=True)
    gaps = gaps[:MAX_GAPS_PER_STORY]

    # follow_up_hint 是模型给的"最想问的那一个"，覆盖最高优先级缺口的问法
    if hint and gaps:
        gaps[0]["question"] = hint[:200]
    elif hint and not gaps:
        gaps.append({
            "gap_type": "missing_detail",
            "question": hint[:200],
            "priority": round(0.5 * (0.6 + 0.4 * confidence), 3),
        })

    return gaps


def estimate_completeness(extraction: dict[str, Any]) -> float:
    """完整度 0~1：有摘要/时间/地点/人物/时代锚点加分，缺口多减分。

    用途：决定这条故事够不够格进入 pending_confirm（太碎就不打扰老人）。
    """
    score = 0.2
    if extraction.get("title"):
        score += 0.1
    if extraction.get("summary"):
        score += 0.15
    time_info = extraction.get("time") or {}
    if time_info.get("value"):
        score += 0.15
    if time_info.get("type") and time_info.get("type") != "relative":
        score += 0.05
    if extraction.get("place"):
        score += 0.1
    if extraction.get("people"):
        score += 0.15
    if extraction.get("era_tags"):
        score += 0.1
    score -= 0.05 * min(len(extraction.get("missing") or []), 4)
    return round(max(0.0, min(1.0, score)), 3)
