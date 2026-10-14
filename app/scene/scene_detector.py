"""场景检测：规则兜底。

设计文档第十五节"规则 + Qwen"：场景判定以 Qwen 分析结果为主
（emotion_analyzer 输出 scene 字段），本模块提供两层规则兜底：
1. Qwen 分析整体失败（fallback scene=conversation）时，按关键词补救一次判断
2. 按时段补充场景线索（清晨/深夜独居老人风险更高）
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime

_SCENE_KEYWORDS: Dict[str, List[str]] = {
    "family_visit": ["女儿来了", "儿子回来", "孙子", "孙女", "孩子们都在", "家里来人了", "老伴在"],
    "mealtime": ["早饭", "早饭吃", "午饭", "晚饭", "中午吃", "晚上吃", "做饭", "吃饭"],
    "outdoor": ["楼下", "公园", "外面", "遛弯", "散步", "菜市场", "广场", "晒太阳"],
    "rest": ["睡不", "失眠", "睡不着", "刚醒", "午休", "午睡"],
    "alone": ["一个人在家", "家里就我", "一个人待", "都没人", "空荡荡"],
}


def detect_by_keywords(message: str) -> Optional[str]:
    """关键词规则：Qwen 失败时的补救。无命中返回 None。"""
    for scene, words in _SCENE_KEYWORDS.items():
        if any(w in message for w in words):
            return scene
    return None


def time_based_hint(now: Optional[datetime] = None) -> Optional[str]:
    """时段线索：清晨/深夜且提到独处时，供策略层提高关注级别。"""
    now = now or datetime.now()
    if 5 <= now.hour < 8:
        return "morning"
    if 18 <= now.hour < 23:
        return "evening"
    if now.hour >= 23 or now.hour < 5:
        return "rest"
    return None


def resolve_scene(qwen_scene: str, message: str,
                  fallback_used: bool) -> Tuple[str, bool]:
    """综合决定最终场景。返回 (scene, is_late_night_alone)。

    - Qwen 正常时直接采用其输出
    - Qwen 降级时用关键词规则 + 时段规则补救
    """
    late_night_alone = False
    hour = datetime.now().hour
    if (hour >= 23 or hour < 5) and ("一个人" in message or "睡不" in message):
        late_night_alone = True

    if not fallback_used and qwen_scene != "conversation":
        return qwen_scene, late_night_alone
    if not fallback_used:
        hint = time_based_hint()
        return (hint or qwen_scene), late_night_alone

    rule_scene = detect_by_keywords(message)
    return rule_scene or qwen_scene, late_night_alone
