"""回忆录仓储层（async）。

一个文件覆盖四张表，按四组分开：
- StoryRepo            life_stories
- ElicitationRepo      story_elicitation_queue
- StoryMediaRepo       story_media
- CompilationRepo      story_compilations

设计约定（与 family.py / scheduler 一致）：
- 仓储只做 CRUD，**不 commit**；由调用方（路由 / 后台任务）决定事务边界。
- 归属校验内建在仓储方法里（`elderly_user_id` 可选参数），避免每个路由重复写 if。

这里同时是两条契约的强制点：
- 契约2：`set_visibility` 在 `visibility_locked=True` 时**直接拒绝**，不可被绕过；
- 契约5：`append_raw` 只追加 `raw_dialogue`，从不修改/删除已有元素。
"""
import logging
from datetime import datetime, timedelta
from typing import Any, Optional, Sequence

from sqlalchemy import func, or_, select

from app.db.models import (
    LifeStory,
    StoryCompilation,
    StoryElicitationQueue,
    StoryMedia,
)

logger = logging.getLogger(__name__)

STORY_STATUSES = {"draft", "pending_confirm", "archived", "discarded"}
VISIBILITIES = {"private", "family", "public"}
FAMILY_VISIBLE = ("family", "public")
GAP_TYPES = {"missing_time", "missing_place", "missing_person", "missing_detail"}
GAP_STATUSES = {"pending", "asked", "answered", "abandoned"}
PERSPECTIVES = {"first_person", "third_person"}
COMPILATION_STATUSES = {"queued", "prompt_ready", "rendering", "done", "failed"}

# set_visibility 的返回码
VIS_OK = "ok"
VIS_LOCKED = "locked"
VIS_NOT_FOUND = "not_found"


class StoryRepo:
    """life_stories 的读写。"""

    def __init__(self, session) -> None:
        self.session = session

    async def create(
        self,
        elderly_user_id: str,
        *,
        title: str = "",
        summary: str = "",
        raw_dialogue: Optional[list[dict]] = None,
        time_type: str = "relative",
        time_value: str = "",
        time_confidence: float = 0.0,
        time_inferred: bool = False,
        era_tags: Optional[list[str]] = None,
        place: str = "",
        people: Optional[list[str]] = None,
        emotion_tone: str = "平淡",
        completeness: float = 0.0,
        status: str = "draft",
        visibility: str = "family",
        visibility_locked: bool = False,
        avoid_flag: bool = False,
        source_msg_ids: Optional[list[int]] = None,
    ) -> LifeStory:
        story = LifeStory(
            elderly_user_id=elderly_user_id,
            title=title,
            summary=summary,
            raw_dialogue=raw_dialogue or [],
            time_type=time_type,
            time_value=time_value,
            time_confidence=time_confidence,
            time_inferred=time_inferred,
            era_tags=era_tags or [],
            place=place,
            people=people or [],
            emotion_tone=emotion_tone,
            completeness=completeness,
            status=status if status in STORY_STATUSES else "draft",
            visibility=visibility if visibility in VISIBILITIES else "family",
            visibility_locked=visibility_locked,
            avoid_flag=avoid_flag,
            source_msg_ids=source_msg_ids or [],
        )
        self.session.add(story)
        await self.session.flush()
        return story

    async def get(self, story_id: int, elderly_user_id: Optional[str] = None) -> Optional[LifeStory]:
        """按 id 取；传 elderly_user_id 时顺带做归属校验（取不到即视为无权/不存在）。"""
        stmt = select(LifeStory).where(LifeStory.id == story_id)
        if elderly_user_id is not None:
            stmt = stmt.where(LifeStory.elderly_user_id == elderly_user_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_by_status(
        self, elderly_user_id: str, status: str, limit: int = 50
    ) -> list[LifeStory]:
        stmt = (
            select(LifeStory)
            .where(LifeStory.elderly_user_id == elderly_user_id, LifeStory.status == status)
            .order_by(LifeStory.created_at.desc(), LifeStory.id.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_archived(self, elderly_user_id: str, limit: int = 500) -> list[LifeStory]:
        return await self.list_by_status(elderly_user_id, "archived", limit)

    async def list_all(self, elderly_user_id: str, limit: int = 500) -> list[LifeStory]:
        """不分状态（老人端 timeline 的 `status=all` 用；家属端不要走这条路）。"""
        stmt = (
            select(LifeStory)
            .where(LifeStory.elderly_user_id == elderly_user_id)
            .order_by(LifeStory.created_at.desc(), LifeStory.id.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_visible_for_family(
        self, elderly_user_id: str, limit: int = 200
    ) -> list[LifeStory]:
        """家属可见集合：仅 archived 且 visibility ∈ (family, public)（契约2）。

        过滤放在服务层，前端拿不到 private 条目，避免"前端隐藏"式伪安全。
        """
        stmt = (
            select(LifeStory)
            .where(
                LifeStory.elderly_user_id == elderly_user_id,
                LifeStory.status == "archived",
                LifeStory.visibility.in_(FAMILY_VISIBLE),
            )
            .order_by(LifeStory.created_at.desc(), LifeStory.id.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def set_status(self, story_id: int, status: str) -> bool:
        if status not in STORY_STATUSES:
            raise ValueError(f"非法 status: {status}")
        story = await self.get(story_id)
        if story is None:
            return False
        story.status = status
        story.updated_at = datetime.now()
        return True

    async def set_visibility(self, story_id: int, visibility: str) -> str:
        """改可见性。返回 VIS_OK / VIS_LOCKED / VIS_NOT_FOUND。

        契约2：创伤故事的 private 是**锁定**的，家属与任何接口都改不回来。
        """
        if visibility not in VISIBILITIES:
            raise ValueError(f"非法 visibility: {visibility}")
        story = await self.get(story_id)
        if story is None:
            return VIS_NOT_FOUND
        if story.visibility_locked:
            logger.info("故事 %s 可见性已锁定（创伤），拒绝改为 %s", story_id, visibility)
            return VIS_LOCKED
        story.visibility = visibility
        story.updated_at = datetime.now()
        return VIS_OK

    async def append_raw(self, story_id: int, fragments: Sequence[dict]) -> bool:
        """只追加原始对话片段（契约5）。

        永远不修改、不删除已有元素；重复片段自动跳过。任何"纠正"都无处落脚——
        偏差只能体现在 time_confidence 上，原文不可变。
        """
        story = await self.get(story_id)
        if story is None:
            return False
        current = list(story.raw_dialogue or [])
        for frag in fragments:
            if frag not in current:
                current.append(frag)
        story.raw_dialogue = current
        story.updated_at = datetime.now()
        return True

    async def mark_avoid(self, story_id: int) -> bool:
        """老人回避过该话题：标记 + 强制 private 且锁定（M4 会调用，M1 先备好）。"""
        story = await self.get(story_id)
        if story is None:
            return False
        story.avoid_flag = True
        story.visibility = "private"
        story.visibility_locked = True
        story.updated_at = datetime.now()
        return True

    async def count_by_status(self, elderly_user_id: str) -> dict[str, int]:
        """各状态计数（M6 日报用）。"""
        rows = (await self.session.execute(
            select(LifeStory.status).where(LifeStory.elderly_user_id == elderly_user_id)
        )).scalars().all()
        result: dict[str, int] = {}
        for status in rows:
            result[status] = result.get(status, 0) + 1
        return result

    async def count_family_visible(
        self, elderly_user_id: str, since: Optional[datetime] = None
    ) -> int:
        """家属可见（已留档 + visibility ∈ family/public）的故事条数。

        传 `since` 时只数「该时刻之后留档的」（M6 日报的「今天/本周新增 N 段」）：
        判据用 `updated_at`——`set_status()` 落档时会刷新它，所以「今天归档的」
        能算准；老遗留行 `updated_at` 为空，天然不落进区间，不会虚报。
        可见性口径与 `list_visible_for_family` 完全一致（契约2）。
        """
        conditions = [
            LifeStory.elderly_user_id == elderly_user_id,
            LifeStory.status == "archived",
            LifeStory.visibility.in_(FAMILY_VISIBLE),
        ]
        if since is not None:
            conditions += [
                LifeStory.updated_at.is_not(None),
                LifeStory.updated_at >= since,
            ]
        stmt = select(func.count()).select_from(LifeStory).where(*conditions)
        return int((await self.session.execute(stmt)).scalar_one() or 0)


class ElicitationRepo:
    """story_elicitation_queue 的读写（M4 使用；M1 负责写入）。"""

    def __init__(self, session) -> None:
        self.session = session

    async def add(
        self, elderly_user_id: str, story_id: int, *,
        question: str, gap_type: str, priority: float = 0.5,
    ) -> StoryElicitationQueue:
        gap = StoryElicitationQueue(
            elderly_user_id=elderly_user_id,
            story_id=story_id,
            question=question[:200],
            gap_type=gap_type if gap_type in GAP_TYPES else "missing_detail",
            priority=max(0.0, min(1.0, priority)),
            status="pending",
        )
        self.session.add(gap)
        await self.session.flush()
        return gap

    async def list_pending(self, elderly_user_id: str, limit: int = 20) -> list[StoryElicitationQueue]:
        stmt = (
            select(StoryElicitationQueue)
            .where(
                StoryElicitationQueue.elderly_user_id == elderly_user_id,
                StoryElicitationQueue.status == "pending",
            )
            .order_by(StoryElicitationQueue.priority.desc(), StoryElicitationQueue.id.asc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def for_story(self, story_id: int) -> list[StoryElicitationQueue]:
        stmt = select(StoryElicitationQueue).where(StoryElicitationQueue.story_id == story_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_candidates(
        self, elderly_user_id: str, now: Optional[datetime] = None, limit: int = 20
    ) -> list[StoryElicitationQueue]:
        """可追问的候选：状态未终结，且 cooldown 已过（或从未问过）。

        `answered` / `abandoned` 一律排除——已经问明白的、或问过两次没回应的，
        不该再打扰老人（契约3 克制）。
        """
        now = now or datetime.now()
        stmt = (
            select(StoryElicitationQueue)
            .where(
                StoryElicitationQueue.elderly_user_id == elderly_user_id,
                StoryElicitationQueue.status.in_(("pending", "asked")),
                or_(
                    StoryElicitationQueue.cooldown_until.is_(None),
                    StoryElicitationQueue.cooldown_until <= now,
                ),
            )
            .order_by(StoryElicitationQueue.priority.desc(), StoryElicitationQueue.id.asc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_asked_since(self, elderly_user_id: str, since: datetime) -> int:
        """`since` 之后问过几次——用于「本会话硬上限」判定。"""
        stmt = select(func.count()).select_from(StoryElicitationQueue).where(
            StoryElicitationQueue.elderly_user_id == elderly_user_id,
            StoryElicitationQueue.asked_at.is_not(None),
            StoryElicitationQueue.asked_at >= since,
        )
        return int((await self.session.execute(stmt)).scalar_one() or 0)

    async def mark_asked(
        self, gap_id: int, *, now: Optional[datetime] = None,
        cooldown_days: int = 3, max_asks: int = 2,
    ) -> str:
        """记录一次主动追问。返回 'asked' 或 'abandoned'。

        「同问题 2 次无回应 → abandoned」：问满 max_asks 次后不再缠着老人，
        状态直接终结（不是"再等等"，是真的不问了这个话题）。
        """
        now = now or datetime.now()
        gap = (await self.session.execute(
            select(StoryElicitationQueue).where(StoryElicitationQueue.id == gap_id)
        )).scalar_one_or_none()
        if gap is None:
            return "not_found"
        gap.ask_count = int(gap.ask_count or 0) + 1
        gap.asked_at = now
        if gap.ask_count >= max_asks:
            gap.status = "abandoned"
        else:
            gap.status = "asked"
            gap.cooldown_until = now + timedelta(days=max(1, cooldown_days))
        return gap.status

    async def mark_answered(
        self, *, story_id: Optional[int] = None, gap_id: Optional[int] = None
    ) -> int:
        """把某条（或某故事下所有）未终结的缺口标为 answered。

        老人后来把时间/地点/人物说清楚了，这些缺口就不该再问。返回受影响条数。
        """
        conditions = [StoryElicitationQueue.status.in_(("pending", "asked"))]
        if gap_id is not None:
            conditions.append(StoryElicitationQueue.id == gap_id)
        if story_id is not None:
            conditions.append(StoryElicitationQueue.story_id == story_id)
        if gap_id is None and story_id is None:
            return 0
        rows = list((await self.session.execute(
            select(StoryElicitationQueue).where(*conditions)
        )).scalars().all())
        for gap in rows:
            gap.status = "answered"
        return len(rows)

    async def mark_abandoned(self, gap_id: int) -> bool:
        gap = (await self.session.execute(
            select(StoryElicitationQueue).where(StoryElicitationQueue.id == gap_id)
        )).scalar_one_or_none()
        if gap is None:
            return False
        gap.status = "abandoned"
        return True

    async def retry_story_gaps(self, story_id: int, *, now: Optional[datetime] = None) -> int:
        """老人主动又聊起这条故事时，把已放弃的缺口放回候选（重新给机会）。"""
        now = now or datetime.now()
        rows = list((await self.session.execute(
            select(StoryElicitationQueue).where(
                StoryElicitationQueue.story_id == story_id,
                StoryElicitationQueue.status == "abandoned",
            )
        )).scalars().all())
        for gap in rows:
            gap.status = "pending"
            gap.ask_count = 0
            gap.cooldown_until = now
        return len(rows)


class StoryMediaRepo:
    """story_media 的读写（M6）。

    注意：本仓储**不管可见性**——照片能不能给家属看，由路由层按故事当下的
    `status`/`visibility` 判定（与 `filter_package_for_family` 同一套口径）。
    仓储只做「查/增/删」，避免把契约判断散落在两处。
    """

    def __init__(self, session) -> None:
        self.session = session

    async def add(
        self, story_id: int, *, type_: str = "photo", url: str = "",
        caption: str = "", uploaded_by: str = "",
    ) -> StoryMedia:
        media = StoryMedia(
            story_id=story_id, type=type_, url=url,
            caption=caption[:200], uploaded_by=uploaded_by,
        )
        self.session.add(media)
        await self.session.flush()
        return media

    async def list_for_story(self, story_id: int) -> list[StoryMedia]:
        stmt = select(StoryMedia).where(StoryMedia.story_id == story_id).order_by(StoryMedia.id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def map_for_stories(
        self, story_ids: Sequence[int]
    ) -> dict[int, list[StoryMedia]]:
        """一次性把多条故事的照片查出来（时间轴用，避免 N+1）。

        空列表直接返回空 dict，不发查询——时间轴空的时候不该多一次往返。
        """
        ids = [int(s) for s in story_ids]
        if not ids:
            return {}
        stmt = (
            select(StoryMedia)
            .where(StoryMedia.story_id.in_(ids))
            .order_by(StoryMedia.story_id, StoryMedia.id)
        )
        result: dict[int, list[StoryMedia]] = {}
        for row in (await self.session.execute(stmt)).scalars().all():
            result.setdefault(row.story_id, []).append(row)
        return result

    async def get(self, media_id: int) -> Optional[StoryMedia]:
        stmt = select(StoryMedia).where(StoryMedia.id == media_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def exists_url(self, url: str) -> bool:
        """是否还有别的记录指向同一个落盘文件。

        照片按内容哈希命名，同一张图重复上传会共用文件；所以删记录前要先问
        一句"还有人引用吗"，否则会把别人正在用的图删掉。
        """
        if not url:
            return False
        stmt = select(StoryMedia.id).where(StoryMedia.url == url).limit(1)
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def remove(self, media_id: int) -> Optional[StoryMedia]:
        """删记录并返回被删的行（调用方据此删盘上的文件）。"""
        media = await self.get(media_id)
        if media is None:
            return None
        await self.session.delete(media)
        return media

    async def delete_for_story(self, story_id: int) -> list[StoryMedia]:
        rows = await self.list_for_story(story_id)
        for row in rows:
            await self.session.delete(row)
        return rows


class CompilationRepo:
    """story_compilations 的读写（M5 使用）。"""

    def __init__(self, session) -> None:
        self.session = session

    async def create(
        self, elderly_user_id: str, *, title: str = "",
        story_ids: Optional[list[int]] = None, perspective: str = "first_person",
        created_by: str = "",
    ) -> StoryCompilation:
        comp = StoryCompilation(
            elderly_user_id=elderly_user_id,
            title=title,
            story_ids=story_ids or [],
            perspective=perspective if perspective in PERSPECTIVES else "first_person",
            status="queued",
            created_by=created_by,
        )
        self.session.add(comp)
        await self.session.flush()
        return comp

    async def get(self, comp_id: int, elderly_user_id: Optional[str] = None) -> Optional[StoryCompilation]:
        stmt = select(StoryCompilation).where(StoryCompilation.id == comp_id)
        if elderly_user_id is not None:
            stmt = stmt.where(StoryCompilation.elderly_user_id == elderly_user_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_user(self, elderly_user_id: str, limit: int = 50) -> list[StoryCompilation]:
        stmt = (
            select(StoryCompilation)
            .where(StoryCompilation.elderly_user_id == elderly_user_id)
            .order_by(StoryCompilation.created_at.desc(), StoryCompilation.id.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def set_prompt_package(
        self, comp_id: int, package: dict[str, Any], model: str = ""
    ) -> bool:
        """写入提示词包并把状态推到 prompt_ready（契约6：到此为止，不生成画面）。"""
        comp = await self.get(comp_id)
        if comp is None:
            return False
        comp.prompt_package = package
        comp.prompt_model = model
        comp.status = "prompt_ready"
        return True

    async def delete(self, comp_id: int, elderly_user_id: Optional[str] = None) -> bool:
        comp = await self.get(comp_id, elderly_user_id)
        if comp is None:
            return False
        await self.session.delete(comp)
        return True
