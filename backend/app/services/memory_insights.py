"""记忆图谱 + 回忆录流水线统计（家属看板用）+ 老人端画像（journey 用）。

几个口径：
- build_memory_graph：把 memories 抽成「人物 × 话题」共现网络。
  分词用 jieba（纯 Python，无二进制依赖）；人物 = jieba 人名(nr) + 称谓正则，
  与前端 personExtract.ts 的 RELATION_WORDS 保持同步；话题 = 名词(n)去停用词。
- build_memoir_pipeline：回忆录从「线索」到「家属可见」的四段流程计数。
- build_journey：老人端「人生河」（AI 成长 + 时光河）。
- build_portrait：老人端「AI 眼中的你」画像卡。

隐私边界（契约2，比 rhythm/care-index 更严格）：
- 图谱只用记忆文本抽**词**，不返回任何 memory 原文；
- 流水线只统计**家属可见集合**（archived + visibility ∈ family/public），
  被标记私密/锁定的条目连计数都不出现——本模块甚至不查它们的 status；
- portrait / journey 是**老人本人**接口（路由层 require_elderly），
  可以返回老人自己的记忆内容与画像，不存在外泄问题。
"""
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

import jieba
import jieba.posseg as pseg
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LifeStory
from app.repositories.profile_repo import ConversationRepo, MemoryRepo, ProfileRepo
from app.repositories.story_repo import ElicitationRepo, StoryRepo

# 人物称谓：与前端 src/lib/personExtract.ts 的 RELATION_WORDS 同步
# （前端没有的「阿姨/保姆/护工」是居家照护角色，图谱侧补充）
RELATION_WORDS = [
    '女儿', '儿子', '老伴', '爱人', '妻子', '丈夫', '儿媳妇', '儿媳', '女婿',
    '孙子', '孙女', '外孙女', '外孙', '父亲', '母亲', '爸爸', '妈妈', '公公', '婆婆',
    '哥哥', '弟弟', '姐姐', '妹妹', '老友', '老同事', '同事', '邻居', '朋友', '战友', '同学',
    '阿姨', '保姆', '护工',
]
RELATION_RE = re.compile(f"({'|'.join(RELATION_WORDS)})([\\u4e00-\\u9fa5]{{0,3}})")

# 话题停用词：通用词 + 记忆抽取模板常见残留（高频但无信息量）
TOPIC_STOPWORDS = {
    '老人', '老人家', '时候', '小时候', '以前', '一天', '今年',
    '去年', '昨天', '今天', '早上', '晚上', '中午', '下午', '时间', '事情',
    '东西', '方面', '情况', '习惯', '知道', '觉得', '曾经', '现在',
    '地方', '生活', '家里', '自己', '大家', '什么', '怎么',
    '经历', '外地', '儿女',
}
# jieba 会把「白面馒头」这类食物专名误判为人名(nr)：专名需在至少 2 条
# 不同记忆里出现才算人物，孤证名字对图谱没有意义
MIN_PERSON_MENTIONS = 2

MAX_TOPICS = 12
MAX_PERSONS = 8


def _extract_persons_topics(content: str) -> Tuple[Set[str], Set[str]]:
    """一条记忆 → (人物集合, 话题集合)。"""
    persons: Set[str] = set()
    topics: Set[str] = set()
    if not content:
        return persons, topics
    for word, flag in pseg.cut(content):
        if len(word) < 2 or word in TOPIC_STOPWORDS:
            continue
        if flag.startswith('nr'):
            persons.add(word)  # 专名：王奶奶 / 老李 / 小芳
        elif flag.startswith('n') and word not in RELATION_WORDS:
            topics.add(word)
    for m in RELATION_RE.finditer(content):
        persons.add(m.group(1))  # 称谓：女儿 / 老伴
    return persons, topics


async def build_memory_graph(
    session: AsyncSession, elderly_id: str, elderly_name: str = ""
) -> Dict[str, Any]:
    """人物 × 话题共现图谱。老人本人是中心，不进人物节点。"""
    memories = await MemoryRepo(session).list_all(elderly_id)

    # 第一遍：候选统计（人物含称谓 + jieba 专名，专名稍后按出现条数过滤）
    raw_person_tf: Counter = Counter()
    topic_tf: Counter = Counter()
    pair_tf: Counter = Counter()
    for m in memories:
        persons, topics = _extract_persons_topics(m.content or "")
        if elderly_name:
            persons.discard(elderly_name)
        raw_person_tf.update(persons)
        topic_tf.update(topics)
        for p in persons:
            for t in topics:
                pair_tf[(p, t)] += 1

    # 第二遍：称谓直接保留；jieba 专名需在至少 MIN_PERSON_MENTIONS 条记忆里出现
    # （滤掉「白面馒头」这类被误判为人名的食物/物品专名）
    top_persons = [
        p for p, c in raw_person_tf.most_common()
        if p in RELATION_WORDS or c >= MIN_PERSON_MENTIONS
    ][:MAX_PERSONS]
    top_topics = [t for t, _ in topic_tf.most_common(MAX_TOPICS)]
    person_set, topic_set = set(top_persons), set(top_topics)
    edges = [
        {"person": p, "topic": t, "count": c}
        for (p, t), c in pair_tf.most_common()
        if p in person_set and t in topic_set
    ]

    return {
        "user_id": elderly_id,
        "elderly_name": elderly_name,
        "memory_count": len(memories),
        "persons": [
            {"label": p, "count": raw_person_tf[p]} for p in top_persons
        ],
        "topics": [
            {"label": t, "count": topic_tf[t]} for t in top_topics
        ],
        "edges": edges,
    }


async def build_memoir_pipeline(
    session: AsyncSession, elderly_id: str
) -> Dict[str, Any]:
    """回忆录四段流水线：线索 → 留档 → 隐私分级 → 家属可见。

    计数全部落在**家属可见集合**内；私密/锁定条目不参与任何统计
    （契约2：对家属等同于不存在）。
    """
    # ① 线索捕捉： elicitation 队列的流程状态（不含追问问题内容）
    elicit_counts = await ElicitationRepo(session).count_by_status(elderly_id)

    # ②~④ 只算家属可见的回忆
    visible = await StoryRepo(session).list_visible_for_family(elderly_id)
    visibility_counts: Counter = Counter(s.visibility for s in visible)
    era_counter: Counter = Counter()
    for s in visible:
        for tag in (s.era_tags or []):
            era_counter[tag] += 1

    stages = [
        {
            "key": "elicit",
            "label": "① 捕捉线索",
            "detail": "聊天中发现值得追问的往事缺口，系统先记下来",
            "items": [
                {"label": "待回答", "count": elicit_counts.get("pending", 0)},
                {"label": "已回答", "count": elicit_counts.get("answered", 0)},
                {"label": "已放弃", "count": elicit_counts.get("abandoned", 0)},
            ],
        },
        {
            "key": "archive",
            "label": "② 整理留档",
            "detail": "把零散对话整理成带时间、人物、基调的结构化回忆",
            "items": [
                {"label": "已留档", "count": len(visible)},
            ],
        },
        {
            "key": "privacy",
            "label": "③ 隐私分级",
            "detail": "老人决定每条回忆给谁看；私密和锁定的不进入家属视图",
            "items": [
                {"label": "家人可见", "count": visibility_counts.get("family", 0)},
                {"label": "完全公开", "count": visibility_counts.get("public", 0)},
            ],
        },
        {
            "key": "family",
            "label": "④ 家属可见",
            "detail": "最终出现在看板「回忆录」时间轴里的条目",
            "items": [
                {"label": "时间轴条目", "count": len(visible)},
            ],
        },
    ]

    return {
        "user_id": elderly_id,
        "stages": stages,
        "era_tags": [
            {"label": tag, "count": c} for tag, c in era_counter.most_common(6)
        ],
        "privacy_note": "被老人标记为私密或锁定的回忆不会进入本视图，计数也不显示。",
    }


# ---------- 老人端「人生河」 ----------
#
# 与家属端流水线相反，这里给老人本人看：AI 对自己的了解在增长，
# 以及自己一生的回忆按年代汇成一条河。数据全部来自老人自己，
# 路由层用 require_elderly 保证只有本人能看。

# 人生阶段排序：按 era_tags 关键词命中（从早到晚）
ERA_STAGES: List[Tuple[str, Tuple[str, ...]]] = [
    ("童年时光", ("小时候", "童年")),
    ("知青年代", ("知青年代", "插队", "知青")),
    ("票证年代", ("票证年代",)),
    ("改革开放初期", ("改革开放",)),
    ("下岗改制", ("下岗", "改制")),
    ("近年时光", ()),
]

# 情绪基调 → 颜色语义（前端同映射）
TONE_COLORS: Dict[str, str] = {
    "温暖": "amber",
    "开心": "amber",
    "感激": "amber",
    "辛酸": "blue",
    "难过": "blue",
    "伤感": "blue",
    "平淡": "gray",
    "平静": "gray",
}

GROWTH_MONTHS = 6


def era_stage_of(era_tags: Optional[List[str]], time_value: str = "") -> str:
    """回忆落入哪个人生阶段：先看 era_tags，再看 time_value 文本。

    文本里只有年份（如「1985年」）时按历史年代兜底，
    否则会统一掉进「近年时光」——1985 年进厂的故事不该出现在近年。
    """
    tags = list(era_tags or []) + [time_value or ""]
    for stage, keywords in ERA_STAGES:
        if not keywords:
            continue
        if any(k in t for t in tags for k in keywords if k in t):
            return stage

    match = re.search(r"(19\d{2}|20\d{2})", time_value or "")
    if match:
        year = int(match.group(1))
        if year < 1950:
            return "童年时光"
        if year < 1966:
            return "票证年代"
        if year < 1978:
            return "知青年代"
        if year < 1993:
            return "改革开放初期"
        if year < 2006:
            return "下岗改制"
    return ERA_STAGES[-1][0]


async def build_journey(
    session: AsyncSession, elderly_id: str, elderly_name: str = ""
) -> Dict[str, Any]:
    """老人端「人生河」：AI 陪伴成长 + 回忆时光河。"""
    # --- AI 成长：近 6 个月记忆积累 ---
    memories = await MemoryRepo(session).list_all(elderly_id)
    monthly: Dict[str, Counter] = {}
    first_at = None
    for m in memories:
        if not m.created_at:
            continue
        if first_at is None or m.created_at < first_at:
            first_at = m.created_at
        month = m.created_at.strftime("%Y-%m")
        monthly.setdefault(month, Counter())[m.memory_type or "general"] += 1

    now = datetime.now()
    months = []
    for i in range(GROWTH_MONTHS - 1, -1, -1):
        y, mo = now.year, now.month - i
        while mo <= 0:
            mo += 12
            y -= 1
        key = f"{y:04d}-{mo:02d}"
        by_type = monthly.get(key, Counter())
        months.append({
            "month": key,
            "count": sum(by_type.values()),
            "by_type": dict(by_type),
        })
    this_month = sum(1 for m in memories if m.created_at and m.created_at.strftime("%Y-%m") == now.strftime("%Y-%m"))

    # --- 时光河：老人自己的全部回忆，按人生阶段汇流 ---
    # 只 select 用到的列：避开 raw_dialogue 等大 JSON 字段，加载更快，
    # 也不会因为历史坏行（非 JSON 字符串）让整页 500
    stmt = (
        select(
            LifeStory.id,
            LifeStory.title,
            LifeStory.summary,
            LifeStory.time_value,
            LifeStory.era_tags,
            LifeStory.emotion_tone,
            LifeStory.completeness,
            LifeStory.visibility,
        )
        # 只统计**已留档**的故事：草稿/待确认还在回忆录里打磨，
        # 弃用的故事也不该出现在人生河上。这样河里的数量和《人生之书》一致。
        .where(
            LifeStory.elderly_user_id == elderly_id,
            LifeStory.status == "archived",
        )
        .order_by(LifeStory.id.asc())
        .limit(200)
    )
    rows = (await session.execute(stmt)).all()
    stage_map: Dict[str, List[Dict[str, Any]]] = {s: [] for s, _ in ERA_STAGES}
    for sid, title, summary, time_value, era_tags, tone, completeness, visibility in rows:
        stage = era_stage_of(era_tags, time_value or "")
        stage_map[stage].append({
            "id": sid,
            "title": title or "一段回忆",
            "summary": summary or "",
            "time_value": time_value or "",
            "era_label": stage,
            "emotion_tone": tone or "平淡",
            "tone_color": TONE_COLORS.get(tone or "", "gray"),
            "completeness": completeness or 0.0,
            "visibility": visibility,
        })
    river_stages = [
        {"label": stage, "stories": stage_map[stage]}
        for stage, _ in ERA_STAGES
    ]

    days_together = (now - first_at).days if first_at else 0

    return {
        "user_id": elderly_id,
        "elderly_name": elderly_name,
        "memory_count": len(memories),
        "days_together": days_together,
        "first_memory_at": first_at.isoformat() if first_at else None,
        "this_month_memories": this_month,
        "growth_months": months,
        "river_stages": river_stages,
        "river_total": len(rows),
        "generated_at": now.isoformat(),
    }


# ---------- 老人端「AI 眼中的你」 ----------

async def build_portrait(
    session: AsyncSession, elderly_id: str, elderly_name: str = ""
) -> Dict[str, Any]:
    """AI 视角的画像卡：爱好 / 重要的人 / 常聊话题 / 作息习惯 / 小心避开的话题。

    给老人本人看的（require_elderly），可以用画像与记忆内容。
    """
    profile = await ProfileRepo(session).get(elderly_id)
    memories = await MemoryRepo(session).list_all(elderly_id)

    # 爱好：画像登记的兴趣 + 记忆里抽出的兴趣词
    interests: List[str] = list(profile.interests or []) if profile else []
    favorite_music: List[str] = list(profile.favorite_music or []) if profile else []
    taboos: List[str] = list(profile.taboos or []) if profile else []
    interest_words: Counter = Counter()
    for m in memories:
        if m.memory_type in ("interest", "preference"):
            _persons, topics = _extract_persons_topics(m.content or "")
            interest_words.update(topics)

    # 重要的人 + 常聊话题：复用记忆图谱的抽取
    # 专名过滤与 build_memory_graph 同口径：jieba 会把食物/物品误判成人名(nr)，
    # 孤证专名不算人物（「白面馒头」教训）；称谓不受此限
    person_tf: Counter = Counter()
    topic_tf: Counter = Counter()
    for m in memories:
        persons, topics = _extract_persons_topics(m.content or "")
        if elderly_name:
            persons.discard(elderly_name)
        person_tf.update(persons)
        topic_tf.update(topics)
    top_persons = [
        {"label": p, "count": c}
        for p, c in person_tf.most_common(3)
        if p in RELATION_WORDS or c >= MIN_PERSON_MENTIONS
    ]

    # 作息习惯：老人发言最集中的时段（复用节律口径）
    now = datetime.now()
    since = now - timedelta(days=28)
    tags = await ConversationRepo(session).conversation_tags_since(
        elderly_id, since, role="user"
    )
    hour_tf: Counter = Counter()
    for row in tags:
        created_at = row[0]
        if created_at:
            hour_tf[created_at.hour] += 1
    habit_hour = hour_tf.most_common(1)[0][0] if hour_tf else None
    if habit_hour is None:
        habit_text = "还没摸清你的作息，多聊几天就知道了"
    elif habit_hour < 6:
        habit_text = f"你总在凌晨 {habit_hour} 点前后还在找我，晚上要早点休息"
    elif habit_hour < 12:
        habit_text = f"你总在上午 {habit_hour} 点左右来找我聊天"
    elif habit_hour < 18:
        habit_text = f"你总在下午 {habit_hour} 点左右来找我聊天"
    else:
        habit_text = f"你总在晚上 {habit_hour} 点左右来找我聊天"

    first_at = min(
        (m.created_at for m in memories if m.created_at), default=None
    )
    days_together = (now - first_at).days if first_at else 0

    return {
        "user_id": elderly_id,
        "elderly_name": elderly_name,
        "memory_count": len(memories),
        "days_together": days_together,
        "interests": interests[:8] + [w for w, _ in interest_words.most_common(8) if w not in interests][:6],
        "favorite_music": favorite_music[:6],
        "taboos": taboos[:6],
        "top_persons": top_persons,
        "top_topics": [
            {"label": t, "count": c} for t, c in topic_tf.most_common(8)
        ],
        "habit_hour": habit_hour,
        "habit_text": habit_text,
        "generated_at": now.isoformat(),
    }
