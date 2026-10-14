"""CompanionPolicy：本地陪伴策略编排（设计文档第十四、十五节）。

原则（第十五节）：不要让 Qwen 完全控制系统行为。
- Qwen 负责"理解"（情绪/意图/场景 → 结构化结果，见 emotion_analyzer）
- 本模块负责"决策"（把分析结果映射成确定性的陪伴动作）
- 最终回复生成仍交给 Qwen，但带上由动作决定的 response_style 与指令

这样系统行为可预期、可测试、可控。
"""
import logging
from dataclasses import dataclass
from typing import Optional

from app.emotion.emotion_analyzer import AnalysisResult

logger = logging.getLogger(__name__)

# 动作枚举（设计文档第十四节）
ACTIONS = {
    "empathetic_chat",          # 共情陪伴
    "continue_listening",       # 继续倾听
    "ask_gentle_question",      # 温和提问
    "recommend_music",          # 推荐音乐
    "recommend_story",          # 推荐故事
    "recommend_game",           # 推荐游戏
    "recommend_content",        # 通用内容推荐（无聊时）
    "daily_greeting",           # 日常问候
    "encourage_family_contact", # 鼓励联系家人
    "safety_escalation",        # 安全升级（高风险）
}

# 语气风格
STYLES = {
    "warm": "温暖亲切",
    "gentle": "温和耐心",
    "concise": "简洁平和",
    "calm": "平静安抚",
}

# 每种动作给生成阶段的提示语（会注入 System Prompt）
ACTION_HINTS = {
    "empathetic_chat": "先共情，再顺着老人的话自然展开，语气温暖。",
    "continue_listening": "老人正在倾诉，请优先倾听、表示理解，不要急着给建议，最后温和地邀请他继续说。",
    "ask_gentle_question": "用最自然的方式、最多问一个温和的问题，帮助老人把话继续下去。",
    "recommend_music": "结合老人的音乐喜好推荐一首歌，说说为什么觉得适合他现在听。",
    "recommend_story": "给老人讲一个温和的小故事，或邀请他讲自己年轻时的故事。",
    "recommend_game": "提议一个轻松的动脑小游戏（如成语接龙、简单算术），并主动示范怎么玩。",
    "recommend_content": "老人有些无聊，建议一样轻松的活动或内容，一次只建议一样。",
    "daily_greeting": "亲切地问候，自然地关心他今天过得怎么样。",
    "encourage_family_contact": "温和地鼓励老人和子女/家人联系，分享近况，但不要责备家人。",
    "safety_escalation": "",  # 安全指令由 safety.py 提供，这里不重复
}


@dataclass
class PolicyDecision:
    action: str = "empathetic_chat"
    response_style: str = "warm"
    should_continue_conversation: bool = True
    should_recommend_content: bool = False
    action_hint: str = ""
    reason: str = ""           # 决策理由（中文，供前端可视化与可解释性）


class CompanionPolicy:
    """规则引擎：确定性决策。输入分析结果，输出动作（含决策理由）。"""

    def decide(self, analysis: AnalysisResult) -> PolicyDecision:
        d = PolicyDecision()

        # 1) 安全优先：任何高风险都压过其他动作
        if analysis.risk_level == "high":
            d.action = "safety_escalation"
            d.response_style = "calm"
            d.should_continue_conversation = False
            d.reason = "检测到高风险内容（自伤/危及生命），优先安抚并引导求助"
            return d

        # 2) 明确意图优先（老人主动要什么）
        intent_actions = {
            "music_request": ("recommend_music", "老人主动想听音乐"),
            "story_request": ("recommend_story", "老人主动想听故事"),
            "game_request": ("recommend_game", "老人主动想玩游戏"),
            "greeting": ("daily_greeting", "老人在打招呼"),
            "family_talk": ("encourage_family_contact", "老人在谈家人"),
        }
        if analysis.intent in intent_actions:
            action, reason = intent_actions[analysis.intent]
            d.action = action
            d.response_style = self._style_for(analysis)
            d.should_recommend_content = d.action.startswith("recommend_")
            d.action_hint = ACTION_HINTS[d.action]
            d.reason = reason
            return d

        # 3) 情绪驱动的陪伴动作
        emotion_actions = {
            "lonely": ("empathetic_chat", "情绪为孤独，优先共情陪伴"),
            "sad": ("continue_listening", "情绪为难过，优先倾听而非建议"),
            "anxious": ("continue_listening", "情绪为焦虑，优先安抚倾听"),
            "worried": ("continue_listening", "情绪为担忧，优先倾听"),
            "angry": ("continue_listening", "情绪为生气，先让老人把话说完"),
            "bored": ("recommend_content", "情绪为无聊，推荐内容转移注意力"),
            "happy": ("ask_gentle_question", "情绪为开心，顺势温和提问延续"),
            "nostalgic": ("ask_gentle_question", "情绪为怀旧，温和引导回忆"),
            "grateful": ("ask_gentle_question", "情绪为欣慰，温和回应"),
            "tired": ("continue_listening", "情绪为疲惫，不打扰式陪伴"),
        }
        if analysis.emotion in emotion_actions:
            d.action, d.reason = emotion_actions[analysis.emotion]
        else:
            # 情绪中性：看意图
            if analysis.intent == "emotional_sharing":
                d.action, d.reason = "continue_listening", "意图为情感倾诉，继续倾听"
            elif analysis.intent == "memory_recall":
                d.action, d.reason = "ask_gentle_question", "意图为唤起回忆，温和提问"
            else:
                d.action, d.reason = "empathetic_chat", "常规聊天，自然共情"

        d.response_style = self._style_for(analysis)
        d.should_recommend_content = d.action == "recommend_content"
        d.action_hint = ACTION_HINTS[d.action]
        return d

    @staticmethod
    def _style_for(a: AnalysisResult) -> str:
        if a.risk_level == "medium":
            return "gentle"
        if a.emotion in ("sad", "anxious", "worried", "angry", "tired"):
            return "gentle"
        if a.emotion in ("happy", "grateful", "nostalgic"):
            return "warm"
        if a.emotion_intensity >= 0.8:
            return "gentle"
        return "warm"

    def style_hint(self, style: str) -> str:
        return STYLES.get(style, "温暖亲切")


# 模块级单例，供路由复用
policy = CompanionPolicy()
