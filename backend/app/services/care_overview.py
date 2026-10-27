"""家属看板聚合：对话节律 + 关怀指数。

两个口径都只做**计数与统计**，不搬运对话原文 / 记忆内容 / 回忆录正文：
- 节律图回答「老人什么时候在聊」（7×24 计数矩阵）；
- 关怀指数回答「近况好不好」（0-100 + 因子明细）。

隐私边界（契约2）：情绪标注与计数给家属看是既有接口行为（/family/.../emotion
与日报统计已有先例），但正文一律不进本模块——这里连 content 字段都不查。
"""
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.family_message_repo import FamilyMessageRepo
from app.repositories.profile_repo import ConversationRepo

WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 情绪词表与 scheduler/jobs/emotion_alert.py、services/digest_service.py 对齐
NEGATIVE_EMOTIONS = {"lonely", "sad", "worried", "anxious", "angry"}
POSITIVE_EMOTIONS = {"happy", "calm", "grateful"}
# neutral / miss 等算中性，不计入情绪因子的分子分母

# 夜间时段（含）：22:00-06:00，凌晨聊天多常意味着睡眠差
NIGHT_HOURS = set(range(22, 24)) | set(range(0, 6))


def _peak(matrix: List[List[int]]) -> Optional[Dict[str, Any]]:
    """7×24 矩阵里的峰值格子（取最大计数，平手取最早）。"""
    best: Optional[Dict[str, Any]] = None
    for wd in range(7):
        for hour in range(24):
            count = matrix[wd][hour]
            if count <= 0:
                continue
            if best is None or count > best["count"]:
                best = {"weekday": wd, "hour": hour, "count": count}
    return best


async def build_chat_rhythm(
    session: AsyncSession, elderly_id: str, days: int = 28
) -> Dict[str, Any]:
    """老人发言的 7×24 节律矩阵（只统计 role=user 的轮次）。

    days 上限 90：再往前数据稀疏，热力图会退化成噪点。
    """
    days = max(7, min(days, 90))
    since = datetime.now() - timedelta(days=days)
    rows = await ConversationRepo(session).conversations_since(
        elderly_id, since, role="user"
    )

    matrix = [[0] * 24 for _ in range(7)]
    active_days = set()
    night_rounds = 0
    for created_at, _role in rows:
        if created_at is None:
            continue
        wd = created_at.weekday()  # 0=周一
        matrix[wd][created_at.hour] += 1
        active_days.add(created_at.date())
        if created_at.hour in NIGHT_HOURS:
            night_rounds += 1

    total_rounds = sum(sum(row) for row in matrix)
    return {
        "user_id": elderly_id,
        "days": days,
        "matrix": matrix,
        "weekday_labels": WEEKDAY_LABELS,
        "total_rounds": total_rounds,
        "active_days": len(active_days),
        "peak": _peak(matrix),
        "night_rounds": night_rounds,
        "night_ratio": round(night_rounds / total_rounds, 4) if total_rounds else 0.0,
        "generated_at": datetime.now().isoformat(),
    }


async def build_care_index(session: AsyncSession, elderly_id: str) -> Dict[str, Any]:
    """关怀指数（0-100）= 情绪 40 + 活跃 30 + 沉默 20 + 家庭联结 10。

    四个因子都可解释、可复算：每个因子返回 score/max/detail，
    前端直接渲染分解条，不需要额外口径文档。
    """
    now = datetime.now()
    week_ago = now - timedelta(days=7)

    # --- 因子 1：情绪状态（40 分）---
    records = await ConversationRepo(session).emotions_since(elderly_id, week_ago)
    if records:
        pos = sum(1 for r in records if r.emotion in POSITIVE_EMOTIONS)
        neg = sum(1 for r in records if r.emotion in NEGATIVE_EMOTIONS)
        judged = pos + neg
        pos_ratio = pos / judged if judged else 0.5
        avg_intensity = sum(r.intensity or 0.0 for r in records) / len(records)
        # 正面比例占 35 分，交流投入度（平均强度）占 5 分
        emotion_score = round(pos_ratio * 35 + min(avg_intensity, 1.0) * 5)
        emotion_detail = (
            f"近 7 天 {len(records)} 次情绪记录，正面 {pos} 次 / 负面 {neg} 次"
        )
    else:
        # 没有数据时不冤枉也不偏袒：给一半分并说明
        emotion_score = 20
        emotion_detail = "近 7 天暂无情绪记录，暂按中间值计"

    # --- 因子 2：聊天活跃（30 分）---
    conv_rows = await ConversationRepo(session).conversations_since(
        elderly_id, week_ago, role="user"
    )
    active_days = {r[0].date() for r in conv_rows if r[0] is not None}
    activity_score = round(len(active_days) / 7 * 30)
    activity_detail = f"近 7 天有 {len(active_days)} 天聊过天"

    # --- 因子 3：沉默风险（20 分）---
    last_at = await ConversationRepo(session).last_conversation_at(elderly_id)
    if last_at is None:
        silence_days = 99
        silence_detail = "还没有开始聊天"
    else:
        silence_days = max(0, (now - last_at).days)
        silence_detail = f"最近一次聊天在 {silence_days} 天前"
    silence_score = max(0, 20 - silence_days * 5)

    # --- 因子 4：家庭联结（10 分）：近 7 天家属↔老人留言互动 ---
    bond_count = await FamilyMessageRepo(session).count_between(
        elderly_id, week_ago
    )
    bond_score = round(min(bond_count, 4) / 4 * 10)
    bond_detail = f"近 7 天家人互动 {bond_count} 条"

    score = emotion_score + activity_score + silence_score + bond_score
    if score >= 75:
        level = "good"
    elif score >= 50:
        level = "watch"
    else:
        level = "risk"

    # advice 跟着**最弱的因子**走，而不是只看总分——否则会出现
    # 「已经连续沉默多天」配一张「1 天前还聊过」的明细，自相矛盾。
    factors = [
        {"key": "emotion", "label": "情绪状态", "score": emotion_score, "max": 40, "detail": emotion_detail},
        {"key": "activity", "label": "聊天活跃", "score": activity_score, "max": 30, "detail": activity_detail},
        {"key": "silence", "label": "沉默风险", "score": silence_score, "max": 20, "detail": silence_detail},
        {"key": "bond", "label": "家庭联结", "score": bond_score, "max": 10, "detail": bond_detail},
    ]
    if level == "good":
        advice = "状态不错，保持日常陪伴就好。"
    else:
        # 平手时沉默最紧急，其次活跃、情绪、联结
        priority = {"silence": 0, "activity": 1, "emotion": 2, "bond": 3}
        weakest = min(
            factors, key=lambda f: (f["score"] / f["max"], priority[f["key"]])
        )
        if weakest["key"] == "silence" and last_at is None:
            advice = "老人还没有开始聊天，先发条问候打个招呼吧。"
        elif weakest["key"] == "silence" and silence_days >= 3:
            advice = f"已经 {silence_days} 天没聊天了，建议尽快联系或上门看看。"
        elif weakest["key"] == "silence":
            advice = "最近聊天频率偏低，抽空打个电话吧。"
        elif weakest["key"] == "emotion":
            advice = "近期的情绪记录里负面偏多，聊天时多留意、多陪伴。"
        elif weakest["key"] == "activity":
            advice = "这一周聊天的天数不多，固定时间问候一句也好。"
        else:
            advice = "家人互动偏少，一句问候就能让老人高兴半天。"

    return {
        "user_id": elderly_id,
        "score": score,
        "level": level,
        "advice": advice,
        "factors": factors,
        "generated_at": now.isoformat(),
    }


# ---------- 陪伴需求信号 ----------
#
# 关怀指数回答"近况好不好"，这里回答"老人在要什么"。
# 信号从 conversations 的 scene / intent / current_topic 聚合（只读标注字段，
# 不读正文），按"近 7 天 vs 前 7 天"给趋势。

SIGNAL_RULES: List[Dict[str, Any]] = [
    {
        "key": "loneliness",
        "label": "孤独 / 无聊",
        "icon": "🌙",
        "topics": ["无聊", "孤独", "闷", "没意思", "没劲", "闲得", "冷清"],
        "intents": ["emotional_sharing"],
        "hint": "老人提到无聊或独自在家，陪聊或安排点活动",
    },
    {
        "key": "family_miss",
        "label": "思念家人",
        "icon": "💌",
        "topics": ["女儿", "儿子", "孙子", "孙女", "外孙", "老伴", "孩子", "家人", "想他们"],
        "intents": ["family_talk"],
        "hint": "常提起家人，安排个通话或探望效果好过礼物",
    },
    {
        "key": "health",
        "label": "健康求助",
        "icon": "🩺",
        "topics": ["血压", "心脏", "吃药", "睡不着", "失眠", "疼", "头晕", "感冒", "医院"],
        "intents": ["safety_alert"],
        "hint": "出现健康相关话题，必要时提醒就医或复诊",
    },
    {
        "key": "memory",
        "label": "回忆需求",
        "icon": "📖",
        "topics": ["以前", "当年", "小时候", "过去"],
        "intents": ["memory_recall", "story_request"],
        "hint": "愿意讲往事，顺着问问能帮回忆录攒素材",
    },
    {
        "key": "content",
        "label": "内容 / 娱乐",
        "icon": "🎵",
        "topics": ["音乐", "老歌", "唱歌", "豫剧", "京剧", "电视剧", "收音机"],
        "intents": ["music_request"],
        "hint": "想听歌听戏，放一段他喜欢的节目",
    },
]


def _signal_count(rows: List[Any], rule: Dict[str, Any]) -> int:
    """窗口内命中该信号的轮次：topic 命中 或 intent 命中。"""
    topics = rule.get("topics", [])
    intents = set(rule.get("intents", []))
    n = 0
    for topic, intent, _scene in rows:
        if intent in intents:
            n += 1
            continue
        if topic and any(w in topic for w in topics):
            n += 1
    return n


def _signal_level(count: int) -> str:
    if count >= 5:
        return "high"
    if count >= 2:
        return "medium"
    if count >= 1:
        return "low"
    return "none"


async def build_care_signals(
    session: AsyncSession, elderly_id: str, window_days: int = 7
) -> Dict[str, Any]:
    """陪伴需求信号：近 7 天命中数 + 环比前 7 天 + 每条一句建议。

    只读 scene/intent/topic 标注字段；返回里没有任何对话原文。
    """
    now = datetime.now()
    recent_start = now - timedelta(days=window_days)
    prev_start = now - timedelta(days=window_days * 2)

    rows = await ConversationRepo(session).conversation_tags_since(
        elderly_id, prev_start, role="user"
    )
    recent: List[Any] = []
    prev: List[Any] = []
    for created_at, topic, intent, scene in rows:
        item = (topic or "", intent or "", scene or "")
        if created_at and created_at >= recent_start:
            recent.append(item)
        else:
            prev.append(item)

    signals = []
    for rule in SIGNAL_RULES:
        count = _signal_count(recent, rule)
        prev_count = _signal_count(prev, rule)
        signals.append({
            "key": rule["key"],
            "label": rule["label"],
            "icon": rule["icon"],
            "count": count,
            "prev": prev_count,
            "delta": count - prev_count,
            "level": _signal_level(count),
            "hint": rule["hint"],
        })
    # 命中多的排前面，方便家属一眼看到重点
    signals.sort(key=lambda s: s["count"], reverse=True)

    # 近 7 天话题 top5（只看词，不看内容）
    topic_tf: Counter = Counter(
        t for t, _i, _s in recent if t
    )
    scene_tf: Counter = Counter(s for _t, _i, s in recent if s)

    return {
        "user_id": elderly_id,
        "window_days": window_days,
        "signals": signals,
        "top_topics": [
            {"label": t, "count": c} for t, c in topic_tf.most_common(5)
        ],
        "scene_summary": {
            "alone": scene_tf.get("alone", 0),
            "silence_checkin": scene_tf.get("silence_checkin", 0),
            "total": len(recent),
        },
        "silence_note": (
            f"近 {window_days} 天有 {scene_tf.get('silence_checkin', 0)} 轮是系统主动问安引发的"
        ),
        "generated_at": now.isoformat(),
    }


# ---------- 机器狗陪伴日志（家属端） ----------

async def build_dog_log(
    session: AsyncSession, elderly_id: str, limit: int = 50
) -> Dict[str, Any]:
    """小狗传话记录：跑了几趟、谁最常带话、老人看了没有。

    只读 category='dog_relay' 的留言（内容是家属自己写的传话，
    给发它的家属看没有越界）。
    """
    rows = await FamilyMessageRepo(session).list_dog_relays(elderly_id, limit)

    relay_re = re.compile(r"^([\u4e00-\u9fa5]{2,4})(?:提醒您|说|想让您知道)")
    relation_tf: Counter = Counter()
    for m in rows:
        match = relay_re.match(m.content or "")
        relation_tf[match.group(1) if match else "家人"] += 1

    total = len(rows)
    read_count = sum(1 for m in rows if m.is_read)
    last_at = rows[0].created_at.isoformat() if rows and rows[0].created_at else None

    return {
        "user_id": elderly_id,
        "total_runs": total,
        "read_count": read_count,
        "unread_count": total - read_count,
        "read_rate": round(read_count / total, 4) if total else 0.0,
        "last_run_at": last_at,
        "top_relations": [
            {"label": r, "count": c} for r, c in relation_tf.most_common(5)
        ],
        "records": [
            {
                "id": m.id,
                "content": m.content,
                "is_read": m.is_read,
                "reaction": m.reaction,
                "created_at": m.created_at.isoformat() if m.created_at else "",
                "read_at": m.read_at.isoformat() if m.read_at else None,
            }
            for m in rows[:15]
        ],
        "generated_at": datetime.now().isoformat(),
    }
