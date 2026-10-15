"""回忆录服务编排：把「提取结果」变成「一条 draft 故事 + 若干缺口」。

这是 /chat 后台任务唯一需要调用的入口，串起三件事：
1. 契约2 判定：创伤 / 老人回避过的内容 → visibility=private 且锁定；
2. 完整度评估：决定 status 是 draft（太碎，不打扰老人）还是 pending_confirm（够格给老人确认）；
3. 缺口排队：交给 gap_detector，供 M4 挑时机追问。

不 commit，事务边界由调用方掌握（与 family.py 的既有约定一致）。
"""
import logging
from typing import Any, Optional

from sqlalchemy import select

from app.db.models import ElderlyProfile, LifeStory, StoryCompilation, StoryMedia
from app.memoir import elicitation
from app.memoir.gap_detector import detect_gaps, estimate_completeness
from app.memoir.timeline import build_timeline
from app.repositories.story_repo import ElicitationRepo, StoryMediaRepo, StoryRepo

logger = logging.getLogger(__name__)

# 情绪基调里属于"创伤"的取值（提取器已归一化，这里再兜一层）
TRAUMA_TONES = {"创伤"}

# 完整度门槛：低于此值只进 draft，不主动请老人确认（契约3 克制）
PENDING_CONFIRM_THRESHOLD = 0.4

# 触发 pending_confirm 的最低模型置信度
MIN_CONFIDENCE_FOR_PROMPT = 0.5


def resolve_visibility(extraction: dict[str, Any], *, avoided: bool = False) -> tuple[str, bool]:
    """决定 (visibility, visibility_locked)。

    契约2：默认 family；创伤或老人回避过的内容强制 private 并锁定，家属不可改回。
    """
    tone = str(extraction.get("emotion_tone") or "")
    if avoided or tone in TRAUMA_TONES:
        return "private", True
    return "family", False


async def ingest(
    session,
    elderly_user_id: str,
    extraction: dict[str, Any],
    user_message: str,
    ai_reply: str = "",
    *,
    avoided: bool = False,
    source_msg_ids: Optional[list[int]] = None,
) -> Optional[LifeStory]:
    """把一轮提取结果落库。返回创建的 LifeStory，参数不合法时返回 None。

    extraction 必须是 story_extractor 归一化后的结构（含 is_life_story=True）。
    """
    if not extraction or not extraction.get("is_life_story"):
        return None

    time_info = extraction.get("time") or {}
    visibility, locked = resolve_visibility(extraction, avoided=avoided)
    completeness = estimate_completeness(extraction)

    confidence = float(extraction.get("confidence") or 0.0)
    status = (
        "pending_confirm"
        if completeness >= PENDING_CONFIRM_THRESHOLD and confidence >= MIN_CONFIDENCE_FOR_PROMPT
        else "draft"
    )

    stories = StoryRepo(session)
    story = await stories.create(
        elderly_user_id,
        title=extraction.get("title", ""),
        summary=extraction.get("summary", ""),
        raw_dialogue=[
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": ai_reply},
        ],
        time_type=time_info.get("type", "relative"),
        time_value=time_info.get("value", ""),
        time_confidence=float(time_info.get("confidence") or 0.0),
        era_tags=extraction.get("era_tags") or [],
        place=extraction.get("place", ""),
        people=extraction.get("people") or [],
        emotion_tone=extraction.get("emotion_tone", "平淡"),
        completeness=completeness,
        status=status,
        visibility=visibility,
        visibility_locked=locked,
        avoid_flag=avoided,
        source_msg_ids=source_msg_ids or [],
    )

    queue = ElicitationRepo(session)
    for gap in detect_gaps(extraction):
        await queue.add(
            elderly_user_id, story.id,
            question=gap["question"], gap_type=gap["gap_type"], priority=gap["priority"],
        )

    # 老人刚把某类信息说清楚了 → 关掉"最近问过的那条故事"里同类缺口，
    # 免得出现"他明明讲了、机器还在问"（M4）
    await elicitation.close_asked_gaps(session, elderly_user_id, extraction)

    logger.info(
        "生平故事入库 user=%s story=%s status=%s visibility=%s locked=%s 完整度=%.2f",
        elderly_user_id, story.id, status, visibility, locked, completeness,
    )
    return story


# ---------- M3：时间轴读取（只读，无任何写路径） ----------

async def load_profile_entries(session, elderly_user_id: str) -> list[str]:
    """画像里可用于 P4 保守时间推断的文本（人生经历 + 家人）。

    读不到画像不算错误：少了它只是少一层推断，时间轴照常渲染。
    """
    prof = (await session.execute(
        select(ElderlyProfile).where(ElderlyProfile.user_id == elderly_user_id)
    )).scalar_one_or_none()
    if prof is None:
        return []
    raw = list(prof.life_experience or []) + list(prof.family or [])
    return [str(x) for x in raw if str(x).strip()]


async def build_timeline_payload(
    session,
    elderly_user_id: str,
    *,
    status: str = "archived",
    family_view: bool = False,
) -> dict[str, Any]:
    """按视角取出故事并编排成三组时间轴。

    - `family_view=True`：只给 `archived` 且 `visibility ∈ (family, public)` 的（契约2），
      过滤在**服务层**做，前端拿不到 private 条目。
    - `status="all"`：老人端可以看到自己的 draft/pending（家属端不开放该开关）。
    """
    repo = StoryRepo(session)
    if family_view:
        stories = await repo.list_visible_for_family(elderly_user_id)
    elif status == "all":
        stories = await repo.list_all(elderly_user_id)
    else:
        stories = await repo.list_archived(elderly_user_id)

    # 照片一次性查好挂上（M6）。这里查的是"这几条故事的全部照片"，
    # 因为 stories 本身已经按视角过滤过——不该出现的故事，它的照片自然也不在。
    media_by_story = await StoryMediaRepo(session).map_for_stories([s.id for s in stories])

    payload = build_timeline(
        stories,
        profile_entries=await load_profile_entries(session, elderly_user_id),
        media_by_story=media_by_story,
    )
    payload["user_id"] = elderly_user_id
    return payload


async def visible_story_ids(session, elderly_user_id: str) -> set[int]:
    """家属当前可见的故事 id 集合（契约2 的统一口径）。

    编排快照过滤、照片读取判定都走这个函数，避免两处口径漂移。
    """
    rows = await StoryRepo(session).list_visible_for_family(elderly_user_id)
    return {s.id for s in rows}


async def load_family_story(session, elderly_user_id: str, story_id: int) -> Optional[LifeStory]:
    """取一条**家属可以看**的故事；不可见或不存在都返回 None。"""
    story = await StoryRepo(session).get(story_id, elderly_user_id)
    if story is None or story.status != "archived":
        return None
    if story.visibility not in ("family", "public"):
        return None
    return story


# ---------- M5：故事板 / 提示词编排 ----------

async def _load_stories_for_compilation(
    session, elderly_user_id: str, story_ids: Optional[list[int]]
) -> list[LifeStory]:
    """取参与编排的故事，**只允许 archived**。

    老人没确认留档的内容不该被做成短片——那等于替他做主，违反契约1。
    传了 story_ids 时逐个校验归属 + 状态，不合法的一律不采（而不是报错），
    免得一个过期的 id 让整个编排失败。
    """
    repo = StoryRepo(session)
    if story_ids:
        stories: list[LifeStory] = []
        for sid in story_ids:
            story = await repo.get(sid, elderly_user_id)
            if story is not None and story.status == "archived":
                stories.append(story)
        return stories
    return await repo.list_archived(elderly_user_id)


async def create_compilation(
    session,
    elderly_user_id: str,
    *,
    title: str = "",
    story_ids: Optional[list[int]] = None,
    perspective: str = "first_person",
    created_by: str = "",
    total_seconds: int = 60,
    builder=None,
) -> tuple[Optional[StoryCompilation], str]:
    """建一次短片编排：落一条 queued 记录 → 同步产出提示词包 → prompt_ready。

    返回 `(compilation, reason)`；没有可用的故事时返回 `(None, "no_stories")`。
    契约6：状态止于 prompt_ready，`video_url` 恒为 None，不调用任何生成服务。
    """
    from app.memoir.storyboard import StoryboardBuilder
    from app.repositories.story_repo import CompilationRepo

    stories = await _load_stories_for_compilation(session, elderly_user_id, story_ids)
    if not stories:
        return None, "no_stories"

    repo = CompilationRepo(session)
    comp = await repo.create(
        elderly_user_id,
        title=title or "我的一段日子",
        story_ids=[s.id for s in stories],
        perspective=perspective,
        created_by=created_by,
    )
    await session.flush()

    builder = builder or StoryboardBuilder()
    package = await builder.build(stories, total_seconds=total_seconds)
    await repo.set_prompt_package(
        comp.id, package, model=getattr(builder, "model_name", "") or ""
    )
    logger.info(
        "短片编排完成 user=%s comp=%s 段数=%s 总时长=%ss llm=%s",
        elderly_user_id, comp.id, len(package.get("scenes", [])),
        package.get("total_seconds"), package.get("llm_used"),
    )
    return comp, "ok"


# ---------- M6：回忆照片（家属 / 老人上传） ----------

async def attach_photo(
    session,
    story: LifeStory,
    *,
    uploader_user_id: str,
    data: bytes,
    content_type: str,
    caption: str = "",
) -> StoryMedia:
    """把一张照片挂到某条故事上。照片不合法时抛 `MediaError`。

    只做两件事：落盘（内容哈希命名）+ 落库。**不碰故事本身**——
    家属上传照片不该改动老人讲过的话（契约5），也不该改变可见性（契约1）。
    """
    from app.memoir import media_service

    ext = media_service.validate_image(data, content_type)
    rel = media_service.save_photo(story.id, data, ext)
    media = await StoryMediaRepo(session).add(
        story.id, url=rel, caption=caption, uploaded_by=uploader_user_id
    )
    logger.info(
        "回忆照片入库 story=%s media=%s by=%s bytes=%s",
        story.id, media.id, uploader_user_id, len(data),
    )
    return media


async def detach_photo(session, media) -> None:
    """删一张照片：先删记录，确认没有别的记录引用同一文件后再删盘。"""
    from app.memoir import media_service

    rel = media.url or ""
    await StoryMediaRepo(session).remove(media.id)
    await session.flush()
    if rel and not await StoryMediaRepo(session).exists_url(rel):
        media_service.remove_photo(rel)


def filter_package_for_family(package: Optional[dict], visible_ids: set[int]) -> Optional[dict]:
    """家属端看提示词包前，按当前可见性**再过滤一次**每段镜头。

    这是契约2 的一道补丁：编排时的快照可能包含当时是 family 可见、
    但后来被老人改成 private（或标了回避）的故事。快照不会自己更新，
    所以在家属读取的这一刻按**当下的**可见集合过滤，而不是信任快照。
    """
    if not package:
        return None
    scenes = [
        s for s in (package.get("scenes") or [])
        if isinstance(s, dict) and s.get("story_id") in visible_ids
    ]
    if not scenes:
        return None
    filtered = dict(package)
    filtered["scenes"] = scenes
    filtered["total_seconds"] = sum(int(s.get("duration_seconds") or 0) for s in scenes)
    return filtered
