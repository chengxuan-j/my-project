"""情绪 / 意图 / 场景分析：调用 Qwen API 输出结构化 JSON（设计文档第八、十七节）。

- 独立的"分析调用"，与"生成回复调用"分开，不把能力混在一个 Prompt
- 输出经过枚举白名单校验，任何失败一律降级为
  fallback emotion=neutral / intent=casual_chat / scene=conversation（第二十七节）
"""
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.llm.qwen_client import LLMError, QwenClient

logger = logging.getLogger(__name__)

VALID_EMOTIONS = {
    "neutral", "lonely", "sad", "bored", "happy", "anxious",
    "angry", "tired", "nostalgic", "grateful", "worried",
}
VALID_INTENTS = {
    "casual_chat", "emotional_sharing", "question", "music_request",
    "story_request", "game_request", "greeting", "memory_recall",
    "advice_request", "family_talk", "health_concern", "safety_alert", "other",
}
VALID_SCENES = {
    "conversation", "alone", "family_visit", "mealtime",
    "morning", "evening", "outdoor", "rest",
}
VALID_NEEDS = {
    "companionship", "listening", "distraction", "information",
    "reminder", "praise", "comfort", "none",
}
VALID_RISKS = {"low", "medium", "high"}

ANALYZE_SYSTEM_PROMPT = """你是老人陪伴系统的情境分析模块。分析老人最新一句话（可参考最近对话），只输出一个 JSON 对象，不输出任何其他文字。

格式与取值范围：
{
  "emotion": "老人最新表达的主要情绪，只能从 neutral/lonely/sad/bored/happy/anxious/angry/tired/nostalgic/grateful/worried 中选一个",
  "emotion_intensity": 0到1之间的小数，表示情绪强烈程度,
  "intent": "只能从 casual_chat/emotional_sharing/question/music_request/story_request/game_request/greeting/memory_recall/advice_request/family_talk/health_concern/safety_alert/other 中选一个",
  "topic": "当前话题，2~6个汉字，如 女儿/天气/老歌",
  "scene": "老人当前所处场景，只能从 conversation/alone/family_visit/mealtime/morning/evening/outdoor/rest 中选一个。老人在家没人陪常说 alone；提到家人在身边用 family_visit；没有线索时用 conversation",
  "need": "老人此刻最需要的，只能从 companionship/listening/distraction/information/reminder/praise/comfort/none 中选一个",
  "risk_level": "low/medium/high。只有当话语涉及自伤、自杀念头、严重身体不适、可能危及生命的情况时才是 high；普通诉苦、孤独、担心是 low 或 medium"
}

判定提示：
- "一个人/没人理/孤单" → emotion=lonely
- "想起以前/年轻时" → emotion=nostalgic
- "无聊/没事干" → emotion=bored
- 提到身体疼痛、不舒服、吃药 → intent=health_concern；如果说"不想活了/活着没意思/伤害自己"之类 → intent=safety_alert 且 risk_level=high
- 请老人帮你做什么（讲故事/唱歌/玩游戏）→ 对应 music_request/story_request/game_request
- 问系统是否记得某事 → memory_recall"""

_JSON_RE = re.compile(r"\{.*\}", re.S)


@dataclass
class AnalysisResult:
    emotion: str = "neutral"
    emotion_intensity: float = 0.0
    intent: str = "casual_chat"
    topic: str = ""
    scene: str = "conversation"
    need: str = "none"
    risk_level: str = "low"
    degraded: bool = False   # 是否走了 fallback（供测试与调试）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "emotion": self.emotion,
            "emotion_intensity": self.emotion_intensity,
            "intent": self.intent,
            "topic": self.topic,
            "scene": self.scene,
            "need": self.need,
            "risk_level": self.risk_level,
            "degraded": self.degraded,
        }


def _validate_str(value: Any, allowed: set, default: str) -> str:
    v = str(value).strip().lower() if isinstance(value, str) else ""
    return v if v in allowed else default


def _validate_float(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _repair_truncated_json(text: str) -> Optional[str]:
    """尝试修复被截断的 JSON（如 max_tokens 不够导致 `{"topic":` 后面没值）。
    策略：找到最后一个完整的 key-value 对，截断后补上 }。"""
    # 找到最后一个完整的值结尾（逗号或引号或数字后跟逗号/换行）
    # 从尾向前找最后一个 `"value"` 或数字后的逗号
    last_comma = max(text.rfind(', '), text.rfind(',"'), text.rfind(',\n'))
    if last_comma == -1:
        # 没有逗号，可能只有一个字段被截断
        # 尝试找最后一个冒号，补 null
        colon = text.rfind(':')
        if colon != -1 and not text[colon:].strip().endswith(('null', 'true', 'false', '"', '}')):
            return text[:colon] + ': null}'
        return None
    # 截到最后一个逗号，补 }
    truncated = text[:last_comma].rstrip().rstrip(',')
    return truncated + '}'


def parse_analysis(text: str) -> Optional[AnalysisResult]:
    """容错解析 Qwen 返回；解析不出合法 JSON 返回 None。"""
    t = text.strip().strip("`")
    t = re.sub(r"^json\s*", "", t, flags=re.I)
    data: Any = None
    try:
        data = json.loads(t)
    except json.JSONDecodeError:
        m = _JSON_RE.search(t)
        if m:
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                # 尝试修复被截断的 JSON
                repaired = _repair_truncated_json(m.group(0))
                if repaired:
                    try:
                        data = json.loads(repaired)
                    except json.JSONDecodeError:
                        return None
                else:
                    return None
    if not isinstance(data, dict):
        return None
    return AnalysisResult(
        emotion=_validate_str(data.get("emotion"), VALID_EMOTIONS, "neutral"),
        emotion_intensity=_validate_float(data.get("emotion_intensity")),
        intent=_validate_str(data.get("intent"), VALID_INTENTS, "casual_chat"),
        topic=str(data.get("topic", ""))[:12],
        scene=_validate_str(data.get("scene"), VALID_SCENES, "conversation"),
        need=_validate_str(data.get("need"), VALID_NEEDS, "none"),
        risk_level=_validate_str(data.get("risk_level"), VALID_RISKS, "low"),
    )


class EmotionAnalyzer:
    """第一次 Qwen 调用：情绪/意图/场景/需求/风险 一次性结构化输出。"""

    def __init__(self, client: Optional[QwenClient] = None) -> None:
        self.client = client or QwenClient()

    async def analyze(self, message: str,
                      recent: Optional[List[Tuple[str, str]]] = None) -> AnalysisResult:
        # 给分析器极少量历史做消歧（"他又没来"需要上文知道"他"是谁）
        context = ""
        if recent:
            tail = [f"{r}: {c[:40]}" for r, c in recent[-4:]]
            context = "最近对话：\n" + "\n".join(tail) + "\n\n"

        messages = [
            {"role": "system", "content": ANALYZE_SYSTEM_PROMPT},
            {"role": "user", "content": context + f"老人最新的话：{message}"},
        ]
        try:
            # 用快模型（默认 qwen-turbo）：结构化 JSON 任务，比主模型快 1~2 秒
            # getattr 兜底：外部注入的 mock client 可能没有该属性
            raw = await self.client.chat(
                messages, temperature=0.0, max_tokens=512,
                model=getattr(self.client, "analysis_model", None),
            )
        except LLMError as e:
            logger.warning("情绪分析调用失败，使用 fallback: %s", e)
            return AnalysisResult(degraded=True)

        result = parse_analysis(raw)
        if result is None:
            logger.warning("情绪分析返回非 JSON，使用 fallback。原文前 120 字: %s", raw[:120])
            return AnalysisResult(degraded=True)
        return result
