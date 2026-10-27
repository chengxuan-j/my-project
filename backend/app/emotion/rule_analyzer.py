# -*- coding: utf-8 -*-
"""规则优先的情境分析（2026-10-19）。

动机：每轮对话的 analyze 是一次 LLM 调用，实测 0.7~1.0s，占前置阶段大头。
但老人日常说的话（"今天天气真好" / "我挺好的" / "女儿打电话来了"）绝大多数是
**简单句 + 明确信号**，用关键词规则几十毫秒就能定级，不需要等 LLM。

设计原则（质量优先于速度，宁可漏判不可错判）：
1. **风险最高优先**：命中自伤/危险词直接判 high 并走 safety_alert，
   *不等 LLM*（安全不能赌延迟）；规则不命中也照旧交给 LLM，不因为规则没提就降级。
2. **保守进入**：只有同时满足下面全部条件才用规则结果——
   - 句子较短（≤ 40 字，长句往往一句话里多层意思）
   - 不含否定歧义词（不/没/别/莫/无）——"我不开心""没意思"规则容易判反
   - 命中了至少一个明确信号（情绪/意图/场景词）
   任一不满足就交给 LLM，**不影响质量，只是少省一点时间**。
3. **topic 不硬猜**：规则只在命中话题词表时填 topic，否则留空
   （topic 影响记忆检索，猜错比空着更糟）。
4. **可观测**：规则命中会打 `emotion_rule_hit` 日志并带命中项，
   方便统计命中率、判断规则表是否需要补词。

命中率参考（见 scripts/probe_rule_analyzer.py）：典型老人日常语句 60%~75%，
其余（复杂句/否定句/无信号寒暄）自动落 LLM。
"""
import logging
import re
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# 句长上限：超过这个长度倾向交给 LLM（长句常含多层语义）
MAX_RULE_CHARS = 40

# 否定/歧义词：出现这些词时规则不判情绪（"不开心"≠happy、"没意思"≠bored）
_NEGATIONS = ("不", "没", "别", "莫", "无", "甭")

# ---------- 风险（最高优先）----------
# 命中即 high，且意图 safety_alert。词表对齐 app/safety 的兜底，宁多勿漏。
_RISK_WORDS = (
    "不想活", "活着没意思", "活着有啥", "想死", "要死", "自杀", "寻短见",
    "伤害自己", "不想拖累", "安眠药", "上吊", "割腕", "跳楼", "喝药",
    "疼得受不了", "喘不上气", "昏过去", "大出血", "站不起来",
)

# ---------- 情绪 ----------
# (关键词, emotion, intensity)；intensity 表示该词自带的情绪强度
_EMOTION_WORDS: Tuple[Tuple[Tuple[str, ...], str, float], ...] = (
    (("开心", "高兴", "快乐", "欢喜", "舒畅", "舒坦", "幸福", "满意", "庆幸", "热闹",
      "不错", "挺好", "还好", "舒服", "惬意", "顺心"), "happy", 0.6),
    (("难过", "伤心", "心酸", "想哭", "哭了一场", "委屈", "掉泪", "难受", "心里难受"), "sad", 0.7),
    (("孤单", "孤独", "冷清", "没人陪", "没人理", "一个人闷"), "lonely", 0.7),
    (("无聊", "闷得慌", "没事干", "闲着"), "bored", 0.6),
    (("担心", "不安", "心事", "放不下", "惦记", "忧虑", "害怕", "心慌"), "anxious", 0.7),
    (("生气", "恼火", "烦死了", "气人", "发火", "赌气"), "angry", 0.8),
    (("累", "乏", "疲惫", "没劲", "腰酸", "腿疼", "熬不住"), "tired", 0.6),
    (("想当年", "想起以前", "回想起", "那会儿", "年轻的时候"), "nostalgic", 0.5),
    (("感谢", "多谢", "谢谢", "亏得", "好在有你"), "grateful", 0.6),
    (("着急", "心急", "怎么办"), "worried", 0.6),
)

# ---------- 场景 ----------
_SCENE_WORDS: Tuple[Tuple[Tuple[str, ...], str], ...] = (
    (("一个人在家", "没人陪我", "家里就我", "自己一个人", "老伴走了", "子女不在"), "alone"),
    (("一家人", "儿子女儿都在", "孙子", "外孙", "全家", "孩子回", "来看我", "来陪我了"), "family_visit"),
    (("吃饭", "早饭", "午饭", "晚饭", "早饭吃过", "晌午饭"), "mealtime"),
    (("早上", "清早", "一早", "天刚亮"), "morning"),
    (("晚上", "夜里", "傍晚", "天黑"), "evening"),
    (("出去", "出门", "散步", "买菜", "遛弯", "公园", "逛街", "晒太阳"), "outdoor"),
    (("睡觉", "午睡", "躺一会儿", "歇会儿", "眯一会儿"), "rest"),
)

# ---------- 意图 ----------
_REQUEST_WORDS: Tuple[Tuple[Tuple[str, ...], str], ...] = (
    (("讲故事", "讲个故事", "说个故事", "想听故事", "讲古", "想听从前"), "story_request"),
    (("唱歌", "来首歌", "放首歌", "听歌", "唱一段", "老歌"), "music_request"),
    (("玩游戏", "下棋", "打牌", "猜谜", "玩个游戏"), "game_request"),
    (("你还记得", "你记得吗", "还记得我", "我说过什么", "昨天问你"), "memory_recall"),
    (("该吃药", "提醒我", "几点了", "别忘了"), "reminder"),
    (("身体", "血压", "血糖", "吃药", "失眠", "睡不着", "睡不好", "便秘", "头晕", "哪儿疼", "不舒服", "看病"), "health_concern"),
    (("女儿", "儿子", "老伴", "儿媳妇", "女婿", "孙子", "家人", "孩子他"), "family_talk"),
    (("怎么办", "该不该", "好不好", "能不能"), "advice_request"),
)

# 话题词表（只填有把握的，抽不到就留空给 LLM）
_TOPIC_WORDS: Tuple[Tuple[str, ...], ...] = (
    ("天气", "下雨", "下雪", "气温", "太阳", "风大", "降温", "降温了"),
    ("身体", "血压", "血糖", "吃药", "睡眠", "失眠", "胃口"),
    ("女儿", "儿子", "老伴", "孙子", "外孙", "儿媳妇", "家人"),
    ("以前", "当年", "小时候", "老家", "老单位", "退休"),
    ("吃饭", "做饭", "买菜", "包子", "饺子", "面条"),
    ("看电视", "听戏", "听广播", "刷手机", "散步", "遛弯", "跳舞"),
    ("花钱", "退休金", "工资", "养老金"),
    ("猫", "狗", "鸟", "花", "养草"),
)


# 纯寒暄：整句只有问候，没有别的内容。
# 这类句子不需要 LLM 判 topic/scene，直接给 greeting 能省 0.7~0.9s，
# 是老人最高频的一句话（"你好/在吗/早上好"）。
_GREETING_RE = re.compile(
    r"^(你好|您好|嗨|哈喽|hello|在吗|在么|早上好|上午好|中午好|下午好|晚上好|我回来了)"
    r"[呀啊呢哈啦~！!。.，,\s]*(在吗|在么)?[呀啊呢哈啦~！!。.，,\s]*$",
    re.I,
)

# 可以安全地按"平常闲聊"处理的 topic（不含身体/家人/钱，避免把关心误判成闲聊）
_SAFE_CASUAL_TOPICS: Tuple[str, ...] = (
    "天气", "下雨", "下雪", "气温", "太阳", "风大", "降温",
    "看电视", "听戏", "听广播", "刷手机", "散步", "遛弯", "跳舞",
    "养花", "花", "猫", "狗", "鸟", "买菜", "做饭",
)


def _safe_topic(text: str) -> str:
    for w in _SAFE_CASUAL_TOPICS:
        if w in text:
            return w
    return ""


def _has_negation(text: str, word: str) -> bool:
    """判断情绪词前 3 个字符内是否带否定词（"不开心"/"真没意思"）。"""
    i = text.find(word)
    if i < 0:
        return False
    window = text[max(0, i - 3):i]
    return any(n in window for n in _NEGATIONS)


def rule_analyze(message: str) -> Optional[dict]:
    """尝试用规则给出分析结果。

    返回 dict（与 AnalysisResult.to_dict() 同构，另加 rule=True 标记），
    或 None 表示"这句规则判不了，请走 LLM"。
    """
    text = (message or "").strip()
    if not text or len(text) > MAX_RULE_CHARS:
        return None

    # --- 风险：最高优先，命中即定，不看句长以外的条件 ---
    for w in _RISK_WORDS:
        if w in text:
            return _result(
                emotion="sad", intensity=0.9, intent="safety_alert",
                topic="", scene="conversation", need="comfort",
                risk="high", hit=f"risk:{w}",
            )

    # --- 纯寒暄：整句只有问候，直接给结果，不等 LLM ---
    if _GREETING_RE.match(text):
        return _result(
            emotion="neutral", intensity=0.0, intent="greeting",
            topic="", scene="conversation", need="companionship",
            risk="low", hit="greeting",
        )

    # --- 其余维度：必须先确认没有否定歧义 ---
    hits = []  # (维度, 命中词, 值)

    for words, emo, inten in _EMOTION_WORDS:
        for w in words:
            if w in text and not _has_negation(text, w):
                hits.append(("emotion", w, (emo, inten)))
                break

    for words, scene in _SCENE_WORDS:
        for w in words:
            if w in text:
                hits.append(("scene", w, scene))
                break

    for words, intent in _REQUEST_WORDS:
        for w in words:
            if w in text:
                hits.append(("intent", w, intent))
                break

    # 没有任何明确信号时：短句 + 安全话题（天气/电视/散步）按平常闲聊处理，
    # 不再为了一个 topic 去等 LLM；带否定词或超长句仍然交给 LLM。
    if not hits:
        if len(text) <= 20 and not any(n in text for n in _NEGATIONS):
            topic = _safe_topic(text)
            if topic:
                return _result(
                    emotion="neutral", intensity=0.0, intent="casual_chat",
                    topic=topic, scene="conversation", need="companionship",
                    risk="low", hit=f"topic:{topic}",
                )
        return None

    emotion, intensity = "neutral", 0.0
    scene, intent = "conversation", "casual_chat"

    for dim, _w, val in hits:
        if dim == "emotion":
            emotion, intensity = val
        elif dim == "scene":
            scene = val
        elif dim == "intent":
            intent = val

    # 情绪跟着意图走：明确是请求/提醒/问句时，情绪权重降低（"给我讲个故事"≠emo）
    if intent in ("story_request", "music_request", "game_request", "reminder"):
        if emotion == "neutral":
            intensity = 0.2

    # need：按情绪/意图映射，缺省 none
    need = "none"
    if intent == "health_concern":
        need = "comfort"
    elif intent == "advice_request":
        need = "listening"
    elif emotion in ("sad", "lonely", "anxious", "worried"):
        need = "comfort" if emotion in ("sad", "anxious", "worried") else "companionship"
    elif intent == "question":
        need = "information"
    elif emotion == "happy":
        need = "praise"

    # topic：只填有把握的
    topic = ""
    for words in _TOPIC_WORDS:
        for w in words:
            if w in text:
                topic = w
                break
        if topic:
            break

    hit_desc = ";".join(f"{d}:{w}" for d, w, _ in hits)
    return _result(emotion, intensity, intent, topic, scene, need,
                   "low", hit=hit_desc)


def _result(emotion: str, intensity: float, intent: str, topic: str,
            scene: str, need: str, risk: str, hit: str) -> dict:
    return {
        "emotion": emotion,
        "emotion_intensity": round(intensity, 2),
        "intent": intent,
        "topic": topic,
        "scene": scene,
        "need": need,
        "risk_level": risk,
        "degraded": False,
        "rule": True,
        "rule_hit": hit,
    }
