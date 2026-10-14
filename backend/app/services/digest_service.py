"""每日陪伴日报：统计 + AI 摘要。

供 scheduler/jobs/daily_digest.py 使用：
- build_stats：把当天 Conversation 列表聚合成统计（轮数/情绪分布/话题/时段）
- summarize：调快模型（qwen-turbo）写一段给家属看的温馨摘要；未配置 Key 或调用失败时
  降级为纯统计文本，保证日报一定能生成
"""
import logging
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List

from app.db.models import Conversation

logger = logging.getLogger(__name__)

# 情绪中文名（与 emotion_analyzer 的枚举对齐；未命中直接用原值）
EMOTION_LABELS: Dict[str, str] = {
    "neutral": "平静",
    "happy": "开心",
    "sad": "难过",
    "lonely": "孤独",
    "worried": "担忧",
    "anxious": "焦虑",
    "angry": "生气",
    "calm": "放松",
    "grateful": "感激",
    "miss": "思念",
}

# 摘要生成的最大输入轮数（防 prompt 过长）
MAX_TURNS_FOR_SUMMARY = 40
# 单条消息截断长度
MAX_CONTENT_CHARS = 200


def _emotion_label(emotion: str) -> str:
    return EMOTION_LABELS.get(emotion, emotion or "平静")


def build_stats(convs: List[Conversation]) -> Dict[str, Any]:
    """把当天对话聚合成统计字典。convs 需按时间正序。"""
    user_msgs = [c for c in convs if c.role == "user"]
    emotions = Counter(c.emotion or "neutral" for c in user_msgs)
    topics = [t for t in (c.current_topic for c in user_msgs) if t]
    topic_counter = Counter(topics)

    hours = sorted({c.created_at.hour for c in convs if c.created_at})
    time_range = ""
    if hours:
        time_range = (
            f"{hours[0]:02d}:00 - {hours[-1]:02d}:00" if len(hours) > 1
            else f"{hours[0]:02d}:00 前后"
        )

    # 主情绪：出现最多的（并列取第一个）
    main_emotion = ""
    if emotions:
        main_emotion = emotions.most_common(1)[0][0]

    return {
        "rounds": len(user_msgs),
        "main_emotion": main_emotion,
        "main_emotion_label": _emotion_label(main_emotion) if main_emotion else "",
        "emotion_dist": [
            {"emotion": e, "label": _emotion_label(e), "count": n}
            for e, n in emotions.most_common(5)
        ],
        "topics": [
            {"topic": t, "count": n} for t, n in topic_counter.most_common(3)
        ],
        "time_range": time_range,
    }


def _fallback_summary(stats: Dict[str, Any]) -> str:
    """无 LLM 时的降级摘要：纯统计口播。"""
    parts: List[str] = []
    parts.append(f"今天和陪伴助手聊了 {stats['rounds']} 轮")
    if stats.get("main_emotion_label"):
        parts.append(f"整体心情{stats['main_emotion_label']}")
    if stats.get("topics"):
        topics = "、".join(t["topic"] for t in stats["topics"][:3])
        parts.append(f"主要聊了{topics}")
    if stats.get("time_range"):
        parts.append(f"活跃时段在{stats['time_range']}")
    return "，".join(parts) + "。"


async def summarize(elderly_name: str, convs: List[Conversation]) -> str:
    """调快模型生成给家属的温馨摘要；失败时降级为统计文本。"""
    stats = build_stats(convs)
    if not convs:
        return ""

    # 组装对话文本（控制长度）
    lines: List[str] = []
    for c in convs[:MAX_TURNS_FOR_SUMMARY]:
        who = "老人" if c.role == "user" else "助手"
        content = (c.content or "").strip().replace("\n", " ")[:MAX_CONTENT_CHARS]
        if content:
            lines.append(f"{who}: {content}")
    dialogue = "\n".join(lines)

    prompt = (
        f"下面是老人「{elderly_name}」今天和 AI 陪伴助手的聊天记录。"
        "请替助手写一段给家属看的日报摘要，要求：\n"
        "1. 100 字以内，语气温暖、像家人之间的报平安；\n"
        "2. 说清老人今天心情如何、聊了什么话题；\n"
        "3. 如有值得关注的细节（身体不适、情绪低落、反复提起某件事），温和提醒家属；\n"
        "4. 只输出摘要正文，不要标题、不要解释。\n\n"
        f"聊天记录：\n{dialogue}"
    )

    try:
        from app.llm.qwen_client import QwenClient

        client = QwenClient()
        if not client.is_configured:
            logger.info("未配置 QWEN_API_KEY，日报摘要使用统计降级")
            return _fallback_summary(stats)
        # 注意：用主模型而非 analysis_model——分析模型可能是 kimi-k3 这类
        # 推理模型，token 会全部耗在思维链上导致 content 为空；
        # 也不传 temperature（kimi-k3 等模型不接受该参数）。
        summary = await client.chat(
            [{"role": "user", "content": prompt}],
            model=client.model,
            max_tokens=300,
        )
        summary = (summary or "").strip()
        if summary:
            return summary
        logger.warning("日报摘要为空，使用统计降级")
    except Exception as e:  # LLM 故障绝不阻断日报推送
        logger.warning("日报摘要生成失败，使用统计降级: %s", e)
    return _fallback_summary(stats)


async def build_digest_payload(
    elderly_name: str, convs: List[Conversation], date_str: str
) -> Dict[str, Any]:
    """组装日报 payload（存进 FamilyMessage.content 的 JSON）。"""
    stats = build_stats(convs)
    summary = await summarize(elderly_name, convs)
    return {"date": date_str, "summary": summary, "stats": stats}


def is_digest_content(content: str) -> bool:
    """判断一条留言 content 是否是日报 JSON（兼容旧格式纯文本）。"""
    return (content or "").lstrip().startswith("{")


def parse_digest_content(content: str) -> Dict[str, Any] | None:
    """解析日报 content；非日报格式返回 None。"""
    import json

    if not is_digest_content(content):
        return None
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(data, dict) and "summary" in data:
        return data
    return None
