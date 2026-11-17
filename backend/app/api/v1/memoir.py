"""回忆录路由：老人端确认（M2）+ 照片（M6）。

契约1 的落点：**确认按钮只在老人端**——
- 本路由下所有接口都挂 `require_elderly`，家属账号一律 403；
- 老人身份从 JWT 取（不接受路径传 user_id，避免伪造）；
- 每条操作再叠一层归属校验（仓储 `get(story_id, elderly_user_id=...)`）。
- 唯一例外是 `GET /memoir/media/{id}`：照片是**双方共读**的，所以它挂
  `get_current_account` 并在内部自行判定「老人本人 / 已绑定且故事可见的家属」。

契约2：家属端不会在这里看到任何东西——pending 卡片对家属不可见也不可代操作。
"""
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.dependencies import get_current_account, require_elderly
from app.db.base import get_db
from app.db.models import Account, LifeStory
from app.memoir import media_service
from app.memoir.presenter import compilation_to_dict, media_to_dict, story_to_dict
from app.memoir import story_chat
from app.memoir.story_service import (
    attach_photo,
    build_timeline_payload,
    create_compilation,
    detach_photo,
)
from app.repositories.profile_repo import FamilyRepo
from app.repositories.story_repo import (
    CompilationRepo,
    ElicitationRepo,
    StoryMediaRepo,
    StoryRepo,
)
from app.schemas import (
    CompilationCreateRequest,
    CompilationItem,
    MemoirTimeline,
    StoryActionRequest,
    StoryDraftNextRequest,
    StoryDraftNextResponse,
    StoryItem,
    StoryManualCreateRequest,
    StoryMediaItem,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["memoir"])

# 允许被确认的状态（已归档再点确认返回 409，避免重复操作）
CONFIRMABLE = {"pending_confirm", "discarded"}
# 允许被弃用的状态（老人对自己的回忆有最终处置权，含撤回已归档的）
DISCARDABLE = {"draft", "pending_confirm", "archived"}

# 短片界面手动保存的草稿在 raw_dialogue 里留的标记。
# 聊天自动归档的回忆没有这个标记，因此不会出现在草稿箱列表里，也就不会被误删。
MANUAL_STORY_ORIGIN = "short_film_draft"


def _is_manual_story(story: LifeStory) -> bool:
    """判断一条故事是不是短片界面自己保存的草稿。"""
    for turn in (story.raw_dialogue or []):
        if isinstance(turn, dict) and turn.get("origin") == MANUAL_STORY_ORIGIN:
            return True
    return False


async def _load_owned(session: AsyncSession, story_id: int, elderly_user_id: str) -> LifeStory:
    """取故事并校验归属；越权与不存在同样返回 404（不泄露存在性）。"""
    story = await StoryRepo(session).get(story_id, elderly_user_id)
    if story is None:
        raise HTTPException(status_code=404, detail="回忆条目不存在")
    return story


@router.post("/memoir/stories", response_model=StoryItem)
async def create_manual_story(
    req: StoryManualCreateRequest,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    """把短片界面的文字或语音转写原文直接存进素材库。

    这是用户明确的“保存”动作，所以直接 archived；默认 private，避免一段只为
    做短片而保存的内容在未确认分享前出现在家属端。保存过程不调用 LLM，输入什么
    就保存什么，保证演示链路确定、可重复。
    """
    content = req.content.strip()
    if len(content) < 2:
        raise HTTPException(status_code=422, detail="故事至少需要 2 个字")
    # 标题取第一句（对话式保存时 content 是多行），截断带省略号，避免半句断在中间
    first_line = next((ln.strip() for ln in content.splitlines() if ln.strip()), "")
    title = req.title.strip() or (first_line[:20] + ("…" if len(first_line) > 20 else ""))

    # 对话式讲故事：把老人原话和小忆的追问一起留底，回看能看清上下文。
    # 沿用契约5 的口径——只追加，不改写；origin 只打在第一条上，供草稿箱识别。
    turns = [
        {"role": t.role, "content": t.content.strip()} for t in req.turns if t.content.strip()
    ]
    if turns:
        raw_dialogue = turns
        raw_dialogue[0]["origin"] = MANUAL_STORY_ORIGIN
        raw_dialogue[0]["input_type"] = req.input_type
    else:
        raw_dialogue = [{
            "role": "user",
            "content": content,
            # origin 用来把「短片界面自己存的草稿」和聊天里自动归档的回忆分开：
            # 只有前者允许在短片界面里直接永久删除，避免误删聊天攒下的记忆。
            "origin": MANUAL_STORY_ORIGIN,
            "input_type": req.input_type,
        }]

    story = await StoryRepo(session).create(
        account.user_id,
        title=title,
        summary=content,
        raw_dialogue=raw_dialogue,
        completeness=1.0,
        status="archived",
        visibility="private",
    )
    await session.commit()
    logger.info(
        "手动保存短片故事 user=%s story=%s input=%s chars=%d turns=%d",
        account.user_id, story.id, req.input_type, len(content), len(raw_dialogue),
    )
    return story_to_dict(story)


@router.post("/memoir/story-draft/next", response_model=StoryDraftNextResponse)
async def story_draft_next(
    req: StoryDraftNextRequest,
    account: Account = Depends(require_elderly),
):
    """对话式讲故事：根据老人刚说的话，给出小忆的下一句。

    无状态——前端把整段对话发上来，服务端只负责"下一句说什么"。
    不设轮次上限、不自动收尾：老人愿意讲就一直陪着讲，随时可以保存。
    模型不可用时有规则兜底，保证这句话一定接得上。
    """
    turns = [{"role": t.role, "content": t.content} for t in req.turns]
    result = await story_chat.next_reply(turns)
    logger.info(
        "故事追问 user=%s turns=%d focus=%s source=%s",
        account.user_id, len(turns), result.get("focus"), result.get("source"),
    )
    return StoryDraftNextResponse(**result)


@router.get("/memoir/manual-stories", response_model=list[StoryItem])
async def list_manual_stories(
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    """短片界面「我存的故事」列表：只返回手动保存的草稿，按时间倒序。

    不返回 speak_text：这段内容只用于做短片，不需要念给老人听。
    """
    stories = await StoryRepo(session).list_archived(account.user_id)
    return [
        story_to_dict(s, with_speech=False)
        for s in stories
        if _is_manual_story(s)
    ]


@router.delete("/memoir/stories/{story_id}")
async def delete_story_permanently(
    story_id: int,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    """永久删除老人自己的故事及其衍生内容。

    短片稿的 prompt_package 里保存着故事原文快照，因此引用该故事的短片稿也必须
    一起删除，否则“故事已删”只是表面删除。照片与追问队列同样清理；共享哈希的
    照片只有确认没有其他记录引用后才删盘。
    """
    story = await _load_owned(session, story_id, account.user_id)
    compilation_repo = CompilationRepo(session)
    compilations = await compilation_repo.list_for_user(account.user_id, limit=5000)
    related_compilations = [c for c in compilations if story_id in list(c.story_ids or [])]
    for comp in related_compilations:
        await compilation_repo.delete(comp.id, account.user_id)

    await ElicitationRepo(session).delete_for_story(story_id)
    media_repo = StoryMediaRepo(session)
    media_rows = await media_repo.delete_for_story(story_id)
    media_paths = {row.url for row in media_rows if row.url}
    await session.delete(story)
    await session.flush()
    removable_paths = [
        rel for rel in media_paths if not await media_repo.exists_url(rel)
    ]
    await session.commit()

    for rel in removable_paths:
        media_service.remove_photo(rel)
    logger.info(
        "永久删除短片故事 user=%s story=%s compilations=%d media=%d",
        account.user_id, story_id, len(related_compilations), len(media_rows),
    )
    return {
        "deleted": True,
        "id": story_id,
        "deleted_compilations": len(related_compilations),
    }


@router.get("/memoir/timeline", response_model=MemoirTimeline)
async def memoir_timeline(
    status: str = Query(
        "archived",
        pattern="^(archived|all)$",
        description="archived=只看已留档（默认）；all=含 draft/pending（老人自查用）",
    ),
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    """老人端：回忆录时间轴（时代轴 / 绝对时间轴 / 未定位 三组）。

    只读接口——契约5 要求这里**没有**任何「纠正时间」的写路径，
    推断出的年份只在响应里标 `time_inferred=True` + 「约」字。
    """
    return await build_timeline_payload(session, account.user_id, status=status)


@router.get("/stories/pending", response_model=list[StoryItem])
async def pending_stories(
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    """老人端：待确认的回忆条目（卡片列表）。"""
    rows = await StoryRepo(session).list_by_status(account.user_id, "pending_confirm")
    return [story_to_dict(s) for s in rows]


@router.get("/stories/{story_id}", response_model=StoryItem)
async def story_detail(
    story_id: int,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    story = await _load_owned(session, story_id, account.user_id)
    return story_to_dict(story)


@router.post("/stories/{story_id}/confirm", response_model=StoryItem)
async def confirm_story(
    story_id: int,
    req: StoryActionRequest | None = None,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    """老人点「留下这段」（或语音确认）→ archived。

    可见性保持不变：创伤故事即便归档也仍是 private（契约2），不会被这次操作放开。
    """
    story = await _load_owned(session, story_id, account.user_id)
    if story.status not in CONFIRMABLE:
        raise HTTPException(status_code=409, detail=f"当前状态 {story.status} 不可确认")

    await StoryRepo(session).set_status(story.id, "archived")
    await session.commit()
    logger.info(
        "回忆归档 user=%s story=%s via=%s visibility=%s",
        account.user_id, story.id, (req.via if req else "button"), story.visibility,
    )
    return story_to_dict(story)


@router.post("/stories/{story_id}/discard", response_model=StoryItem)
async def discard_story(
    story_id: int,
    req: StoryActionRequest | None = None,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    """老人点「先不用」→ discarded（可通过 restore 恢复）。"""
    story = await _load_owned(session, story_id, account.user_id)
    if story.status not in DISCARDABLE:
        raise HTTPException(status_code=409, detail=f"当前状态 {story.status} 不可弃用")

    await StoryRepo(session).set_status(story.id, "discarded")
    await session.commit()
    logger.info("回忆弃用 user=%s story=%s via=%s",
                account.user_id, story.id, (req.via if req else "button"))
    return story_to_dict(story)


@router.post("/stories/{story_id}/restore", response_model=StoryItem)
async def restore_story(
    story_id: int,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    """把弃用的条目放回待确认（契约1：确认权始终在老人手里，所以要求重新确认）。"""
    story = await _load_owned(session, story_id, account.user_id)
    if story.status != "discarded":
        raise HTTPException(status_code=409, detail="只有已弃用的条目可以恢复")

    await StoryRepo(session).set_status(story.id, "pending_confirm")
    await session.commit()
    return story_to_dict(story)


# ---------------------------------------------------------------------------
# M6：回忆照片
#
# 双方都能上传：老人给自家往事补照片，家属给看得见的往事补照片。
# 上传**不改动故事内容、不改动可见性**——只往 story_media 加一行（契约1/5）。
# 读取走鉴权接口而不是静态目录：private 照片不能变成"知道 URL 就能看"。
# ---------------------------------------------------------------------------

async def _can_read_story_media(session: AsyncSession, account: Account, story) -> bool:
    """老人本人始终可读；家属需「已绑定 + 故事当下 archived 且 family/public」。"""
    if account.user_id == story.elderly_user_id:
        return True
    if account.role != "family":
        return False
    bound = await FamilyRepo(session).list_elderly(account.user_id)
    if story.elderly_user_id not in bound:
        return False
    return story.status == "archived" and story.visibility in ("family", "public")


@router.get("/memoir/media/{media_id}")
async def read_media(
    media_id: int,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
):
    """读取一张回忆照片（老人与已绑定家属共读）。

    越权与不存在**同样 404**，不泄露存在性；也不暴露磁盘路径。
    """
    media = await StoryMediaRepo(session).get(media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="找不到这张照片")
    story = await StoryRepo(session).get(media.story_id)
    if story is None or not await _can_read_story_media(session, account, story):
        raise HTTPException(status_code=404, detail="找不到这张照片")

    path = media_service.resolve_path(media.url)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="找不到这张照片")
    return FileResponse(path, media_type=media_service.content_type_for(media.url))


@router.post("/memoir/stories/{story_id}/media", response_model=StoryMediaItem)
async def upload_story_photo(
    story_id: int,
    file: UploadFile = File(...),
    caption: str = Form(""),
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    """老人给自己的回忆补一张照片。"""
    story = await _load_owned(session, story_id, account.user_id)
    data = await file.read()
    try:
        media = await attach_photo(
            session, story,
            uploader_user_id=account.user_id,
            data=data, content_type=file.content_type or "", caption=caption,
        )
    except media_service.MediaError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await session.commit()
    return media_to_dict(media, story.elderly_user_id)


@router.delete("/memoir/media/{media_id}")
async def delete_media(
    media_id: int,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    """老人可删自己故事上的**任何**照片（对自家回忆有最终处置权）。"""
    media = await StoryMediaRepo(session).get(media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="找不到这张照片")
    story = await StoryRepo(session).get(media.story_id)
    if story is None or story.elderly_user_id != account.user_id:
        raise HTTPException(status_code=404, detail="找不到这张照片")

    await detach_photo(session, media)
    await session.commit()
    return {"deleted": True, "id": media_id}


# ---------------------------------------------------------------------------
# M5：故事板 / 提示词编排
#
# 契约6：这里只产出结构化提示词，**没有任何调用视频/图像生成服务的路径**，
# 状态止于 prompt_ready，`video_url` 在响应里恒为 None。
# ---------------------------------------------------------------------------

@router.get("/memoir/compilations", response_model=list[CompilationItem])
async def list_compilations(
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    rows = await CompilationRepo(session).list_for_user(account.user_id)
    return [compilation_to_dict(c) for c in rows]


@router.post("/memoir/compilations", response_model=CompilationItem)
async def create_compilation_endpoint(
    req: CompilationCreateRequest,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    """把已留档的故事排成一条短片故事板（同步产包，2~4 秒量级）。

    只允许用 `archived` 的故事：老人没确认留档的内容不该被做成短片，
    那等于替他做主（契约1）。
    """
    comp, reason = await create_compilation(
        session,
        account.user_id,
        title=req.title,
        story_ids=req.story_ids,
        perspective=req.perspective,
        created_by=account.user_id,
        total_seconds=min(
            req.total_seconds, get_settings().memoir_storyboard_seconds * 3
        ),
    )
    if comp is None:
        raise HTTPException(status_code=409, detail="还没有已留档的回忆，先把它们留下来吧")
    await session.commit()
    return compilation_to_dict(comp)


@router.get("/memoir/compilations/{comp_id}", response_model=CompilationItem)
async def get_compilation(
    comp_id: int,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    comp = await CompilationRepo(session).get(comp_id, account.user_id)
    if comp is None:
        raise HTTPException(status_code=404, detail="找不到这段短片")
    return compilation_to_dict(comp)


@router.delete("/memoir/compilations/{comp_id}")
async def delete_compilation(
    comp_id: int,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    ok = await CompilationRepo(session).delete(comp_id, account.user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="找不到这段短片")
    await session.commit()
    return {"deleted": True, "id": comp_id}
