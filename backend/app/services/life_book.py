"""老人端「人生之书」：把回忆录按人生阶段排版成一本可打印的书。

与 journey 的时光河的区别：时光河是概览（卡片），之书是完整阅读体验
（封面 / 章节扉页 / 正文 / 年代注脚）。数据同样只来自老人本人
（路由层 require_elderly），不做可见性过滤——自己的回忆自己看。
"""
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LifeStory
from app.repositories.profile_repo import ProfileRepo
from app.services.memory_insights import ERA_STAGES, TONE_COLORS, era_stage_of

# 每个章节扉页上的一句引导语（按人生阶段）
CHAPTER_INTROS: Dict[str, str] = {
    "童年时光": "那时的天很蓝，日子很慢，一块糖就能开心一整天。",
    "知青年代": "最好的年华撒在了广阔天地里，苦过，也笑过。",
    "票证年代": "粮票、布票、副食本，日子紧巴巴，人情却浓浓的。",
    "改革开放初期": "世界忽然变大了，处处是机会，也处处是选择。",
    "下岗改制": "那一代人扛下了转折的全部重量，从头再来过。",
    "近年时光": "儿孙绕膝，含饴弄孙，一生的故事都有了回声。",
}


async def build_book(session: AsyncSession, elderly_id: str) -> Dict[str, Any]:
    """我的人生之书：封面 + 按人生阶段分的章节。"""
    profile = await ProfileRepo(session).get(elderly_id)
    name = (profile.name if profile else "") or "一位老人"
    age = profile.age if profile else None

    stmt = (
        select(
            LifeStory.id,
            LifeStory.title,
            LifeStory.summary,
            LifeStory.time_value,
            LifeStory.era_tags,
            LifeStory.emotion_tone,
            LifeStory.completeness,
        )
        .where(LifeStory.elderly_user_id == elderly_id)
        .order_by(LifeStory.id.asc())
        .limit(200)
    )
    rows = (await session.execute(stmt)).all()

    chapters: List[Dict[str, Any]] = []
    stage_map: Dict[str, List[Dict[str, Any]]] = {s: [] for s, _ in ERA_STAGES}
    for sid, title, summary, time_value, era_tags, tone, completeness in rows:
        stage = era_stage_of(era_tags, time_value or "")
        stage_map[stage].append({
            "id": sid,
            "title": title or "一段往事",
            "summary": summary or "",
            "time_value": time_value or "",
            "emotion_tone": tone or "平淡",
            "tone_color": TONE_COLORS.get(tone or "", "gray"),
            "completeness": round(float(completeness or 0.0), 2),
        })

    for stage, _kw in ERA_STAGES:
        stories = stage_map[stage]
        if not stories:
            continue
        chapters.append({
            "stage": stage,
            "intro": CHAPTER_INTROS.get(stage, ""),
            "stories": stories,
        })

    return {
        "user_id": elderly_id,
        "author_name": name,
        "age": age,
        "title": f"{name}的人生之书",
        "chapter_count": len(chapters),
        "story_count": len(rows),
        "chapters": chapters,
        "generated_at": datetime.now().isoformat(),
    }
