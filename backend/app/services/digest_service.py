"""每日陪伴日报：统计 + AI 摘要。

供 scheduler/jobs/daily_digest.py 使用：
- build_stats：把当天 Conversation 列表聚合成统计（轮数/情绪分布/话题/时段）
- memoir_line：把回忆录增量（今天/本周新增几段）拼成一句话
- summarize：调快模型（qwen-turbo）写一段给家属看的温馨摘要；未配置 Key 或调用失败时
  降级为纯统计文本，保证日报一定能生成

回忆录口径（M6）：只统计**家属看得见**的（archived + visibility ∈ family/public），
计数在 job 里用 StoryRepo 算好传进来——本模块不碰数据库，纯拼文案，
这样"看一眼文案就知道会说给家属什么"。
"""
import logging
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional

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


def memoir_sentences(memoir: Optional[Dict[str, Any]]) -> List[str]:
    """把回忆录增量拼成给家属看的口语短句（可能为空）。"""
    if not memoir:
        return []
    today = int(memoir.get("today") or 0)
    week = int(memoir.get("week") or 0)
    total = int(memoir.get("total") or 0)
    out: List[str] = []
    if today == 1:
        out.append("今天留下了一段新回忆")
    elif today > 1:
        out.append(f"今天留下了 {today} 段新回忆")
    elif week > 0:
        out.append(f"这周已经攒下 {week} 段回忆")
    if total > 0:
        out.append(f"回忆录里一共 {total} 段")
    return out


def _fallback_summary(
    stats: Dict[str, Any], memoir: Optional[Dict[str, Any]] = None
) -> str:
    """无 LLM 时的降级摘要：纯统计口播。

    `rounds == 0`（今天只留了回忆、没怎么聊天）时不提"聊了 0 轮"——
    那读起来像在报故障，不是报平安。
    """
    parts: List[str] = []
    rounds = int(stats.get("rounds") or 0)
    if rounds:
        parts.append(f"今天和陪伴助手聊了 {rounds} 轮")
        if stats.get("main_emotion_label"):
            parts.append(f"整体心情{stats['main_emotion_label']}")
        if stats.get("topics"):
            topics = "、".join(t["topic"] for t in stats["topics"][:3])
            parts.append(f"主要聊了{topics}")
        if stats.get("time_range"):
            parts.append(f"活跃时段在{stats['time_range']}")
    parts.extend(memoir_sentences(memoir))
    if not parts:
        return ""
    return "，".join(parts) + "。"


async def summarize(
    elderly_name: str,
    convs: List[Conversation],
    memoir: Optional[Dict[str, Any]] = None,
) -> str:
    """调快模型生成给家属的温馨摘要；失败时降级为统计文本。"""
    stats = build_stats(convs)

    if not convs:
        # 今天只留了回忆、没聊天：不调模型（没什么可总结的），直接给回忆那句
        return _fallback_summary(stats, memoir)

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
        "请替助手写一段给家属看的日报摘要。\n\n"
        "【硬性要求 · 违反任何一条都算失败】\n"
        "1. 只能使用上面聊天记录里**真实出现过**的内容，不得添加记录中"
        "没有的信息——包括天气冷暖、身体状况、心情细节、视觉神态"
        "（如「眼神亮亮的」）等，一律不许写；\n"
        "2. 不得给出记录中没有依据的建议（如「记得添衣」「翻翻老相册」"
        "「多陪陪他」）。记录里没有的事，就不提醒；\n"
        "3. 不要复述统计数字，也不要自己编数字；\n"
        "4. 100 字以内，语气温暖、像家人之间的报平安，说清老人今天"
        "心情如何、聊了什么话题；\n"
        "5. 只输出摘要正文，不要标题、不要解释。\n"
    )
    # 仅在记录里确有依据时才提醒（原来是"如有值得关注的细节…温和提醒家属"，
    # 这句会诱导模型在找不到细节时**发明**一个关注点——2026-10-19 实测
    # 因此生成了"天气转凉，记得帮她添衣"这种全文无依据的话）。
    prompt += (
        "6. 如果聊天记录里老人**明确说出了**身体不适，或情绪持续低落，"
        "可以如实、温和地提一句；没有就不要提，不许推断。\n"
    )
    extra = memoir_sentences(memoir)
    if extra:
        joined = "，".join(extra)
        prompt += (
            "7. 老人今天在整理回忆，请自然地提一句（如「"
            + joined
            + "」），不要用「档案」「录入」「数据」这类词，"
            "也不要显得像在盘点。\n"
        )
    prompt += f"\n聊天记录：\n{dialogue}"

    try:
        from app.llm.qwen_client import QwenClient

        client = QwenClient()
        if not client.is_configured:
            logger.info("未配置 QWEN_API_KEY，日报摘要使用统计降级")
            return _fallback_summary(stats, memoir)
        # 注意：用主模型而非 analysis_model——分析模型可能是 kimi-k3 这类
        # 推理模型，token 会全部耗在思维链上导致 content 为空；
        # 也不传 temperature（kimi-k3 等模型不接受该参数）。
        # 100 字中文约 200 token，给到 250 留点余量；原来是 300，
        # 空间越大模型越容易"补内容"，收紧有助于减少发挥
        summary = await client.chat(
            [{"role": "user", "content": prompt}],
            model=client.model,
            max_tokens=250,
        )
        summary = (summary or "").strip()
        if summary:
            return summary
        logger.warning("日报摘要为空，使用统计降级")
    except Exception as e:  # LLM 故障绝不阻断日报推送
        logger.warning("日报摘要生成失败，使用统计降级: %s", e)
    return _fallback_summary(stats, memoir)


async def build_digest_payload(
    elderly_name: str,
    convs: List[Conversation],
    date_str: str,
    memoir: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """组装日报 payload（存进 FamilyMessage.content 的 JSON）。

    `memoir` 形如 `{"today": 1, "week": 3, "total": 12}`，由 job 端算好
    （只含家属可见的条目）。为 None / 全 0 时不写这个键，前端自然不显示。
    """
    stats = build_stats(convs)
    summary = await summarize(elderly_name, convs, memoir=memoir)
    payload: Dict[str, Any] = {"date": date_str, "summary": summary, "stats": stats}
    if memoir and any(int(memoir.get(k) or 0) for k in ("today", "week", "total")):
        payload["memoir"] = {
            "today": int(memoir.get("today") or 0),
            "week": int(memoir.get("week") or 0),
            "total": int(memoir.get("total") or 0),
        }
    return payload


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
