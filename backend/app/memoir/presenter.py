"""回忆录展示层：把 ORM 行转成对外的 StoryItem / 拼确认语。

从 `api/v1/memoir.py` 抽出来，避免 `app/memoir/timeline.py` 反向依赖 api 层
（timeline 是纯逻辑模块，不该 import 路由）。

契约约束：
- 契约1：`speak_text`（确认语）只在老人端用；家属端一律 `with_speech=False`
- 契约5：本模块**只读**，不做任何时间/内容的"纠正"
"""
from __future__ import annotations

from typing import Optional

from app.db.models import LifeStory, StoryCompilation, StoryMedia
from app.schemas import CompilationItem, StoryItem, StoryMediaItem


def build_confirm_speech(story: LifeStory) -> str:
    """留档时念给老人听的确认语。

    设计样例如：「我记下来了——1968 年您去黑龙江，和老王一起。对吗？」
    这里用「时间 + 地点 + 人物」拼出细节，再补一句摘要，最后请老人确认。
    """
    detail_bits = [x for x in (story.time_value, story.place) if x]
    if story.people:
        person = story.people[0]
        detail_bits.append(f"和{person}" if len(detail_bits) else person)
    core = story.summary or story.title or "您刚说的这段往事"
    if detail_bits:
        return f"我记下来了——{'，'.join(detail_bits)}。{core}，对吗？"
    return f"我记下来了——{core}，对吗？"


def media_to_dict(media: StoryMedia, elderly_user_id: str = "") -> StoryMediaItem:
    """ORM → StoryMediaItem。

    `url` 指向**鉴权**读接口，不暴露磁盘路径，也不暴露上传者的 user_id
    （只给 owner / family 这个角色位，家属之间不必互认身份）。
    """
    uploader = media.uploaded_by or ""
    if not uploader:
        role = "unknown"
    elif uploader == (elderly_user_id or ""):
        role = "owner"
    else:
        role = "family"
    return StoryMediaItem(
        id=media.id,
        type=media.type or "photo",
        caption=media.caption or "",
        url=f"/api/v1/memoir/media/{media.id}",
        uploaded_by_role=role,
        created_at=media.created_at.isoformat() if media.created_at else "",
    )


def story_to_dict(story: LifeStory, *, with_speech: bool = True) -> StoryItem:
    """ORM → StoryItem。

    `with_speech=False` 用于列表/家属端：不生成 TTS 文本，省一层多余字符串
    （也顺带避免家属端拿到"念给老人听"的话术）。
    """
    return StoryItem(
        id=story.id,
        title=story.title or "",
        summary=story.summary or "",
        time_type=story.time_type or "relative",
        time_value=story.time_value or "",
        time_confidence=float(story.time_confidence or 0.0),
        time_inferred=bool(story.time_inferred),
        era_tags=list(story.era_tags or []),
        place=story.place or "",
        people=list(story.people or []),
        emotion_tone=story.emotion_tone or "平淡",
        completeness=float(story.completeness or 0.0),
        status=story.status,
        created_at=story.created_at.isoformat() if story.created_at else "",
        speak_text=build_confirm_speech(story) if with_speech else "",
    )


def compilation_to_dict(
    comp: StoryCompilation, package: Optional[dict] = None
) -> CompilationItem:
    """ORM → CompilationItem。

    `package` 可由调用方传入**已过滤**的版本（家属端要按当下可见性再筛一遍）。
    `rendered` 恒为 False、`video_url` 恒为 None——契约6：本系统不生成画面，
    这里保留字段是为了让前端能明确"当前没有视频可下载"，而不是留一个坑。
    """
    return CompilationItem(
        id=comp.id,
        title=comp.title or "",
        perspective=comp.perspective or "first_person",
        status=comp.status or "queued",
        story_ids=list(comp.story_ids or []),
        prompt_package=package if package is not None else comp.prompt_package,
        created_at=comp.created_at.isoformat() if comp.created_at else "",
        video_url=None,
        rendered=False,
    )
