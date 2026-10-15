"""家属看板：绑定老人 + 查看老人情绪历史 + 查看老人记忆 + 回忆录（只读）+ 告警管理 + 家人留言互动。

回忆录部分（M6）刻意只有三种写操作：给可见往事**补照片**、撤回自己补的照片、
发留言。**没有**确认留档、没有改可见性、没有创建短片——那三样是老人专属
（契约1/2）。照片读接口在 memoir.py（双方共读，那边做鉴权判定）。
"""
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.core.dependencies import get_current_account, require_elderly, require_family
from app.core.events import bus
from app.db.base import get_db
from app.db.models import Account, FamilyMessage
from app.memoir import media_service
from app.memoir.presenter import compilation_to_dict, media_to_dict
from app.memoir.story_service import (
    attach_photo,
    build_timeline_payload,
    detach_photo,
    filter_package_for_family,
    load_family_story,
    visible_story_ids,
)
from app.repositories.account_repo import AccountRepo
from app.repositories.alert_repo import AlertRepo
from app.repositories.family_message_repo import FamilyMessageRepo
from app.repositories.profile_repo import ConversationRepo, FamilyRepo, MemoryRepo
from app.repositories.story_repo import CompilationRepo, StoryMediaRepo, StoryRepo
from app.schemas import (
    AlertResponse,
    BindElderlyRequest,
    CompilationItem,
    MemoirTimeline,
    StoryMediaItem,
)
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/family", tags=["family"])


@router.get("/elderly")
async def my_elderly(
    account: Account = Depends(require_family),
    session: AsyncSession = Depends(get_db),
):
    """家属已绑定的老人列表：返回 elderly_id + username + name（便于前端显示）。"""
    from sqlalchemy import select
    from app.db.models import ElderlyProfile
    repo = FamilyRepo(session)
    ids = await repo.list_elderly(account.user_id)
    if not ids:
        return {"elderly": []}
    # 一次性查所有老人的 username + profile.name
    acc_rows = (await session.execute(
        select(Account).where(Account.user_id.in_(ids))
    )).scalars().all()
    prof_rows = (await session.execute(
        select(ElderlyProfile).where(ElderlyProfile.user_id.in_(ids))
    )).scalars().all()
    name_map = {p.user_id: p.name for p in prof_rows}
    return {"elderly": [
        {
            "elderly_id": a.user_id,
            "username": a.username,
            "name": name_map.get(a.user_id, ""),
        }
        for a in acc_rows
    ]}


@router.post("/bind")
async def bind_elderly(
    req: BindElderlyRequest,
    account: Account = Depends(require_family),
    session: AsyncSession = Depends(get_db),
):
    """家属通过老人的 username + 邀请码绑定。"""
    elderly = await AccountRepo(session).get_by_username(req.elderly_username)
    if elderly is None or elderly.role != "elderly":
        raise HTTPException(status_code=404, detail="老人账号不存在")
    if elderly.invite_code != req.invite_code.upper():
        raise HTTPException(status_code=400, detail="邀请码错误")
    if await FamilyRepo(session).exists(account.user_id, elderly.user_id):
        raise HTTPException(status_code=409, detail="已绑定该老人")
    await FamilyRepo(session).bind(
        account.user_id, elderly.user_id, req.relationship_name
    )
    await session.commit()
    # 取老人姓名（不依赖 relationship lazy load）
    from sqlalchemy import select as sql_select
    from app.db.models import ElderlyProfile as EP
    prof = (await session.execute(
        sql_select(EP).where(EP.user_id == elderly.user_id)
    )).scalar_one_or_none()
    return {
        "elderly_id": elderly.user_id,
        "name": prof.name if prof else "老人家",
    }


@router.get("/elderly/{elderly_id}/emotion")
async def elderly_emotion(
    elderly_id: str,
    limit: int = 20,
    account: Account = Depends(require_family),
    session: AsyncSession = Depends(get_db),
):
    """家属查看已绑定老人的情绪历史。"""
    repo = FamilyRepo(session)
    if elderly_id not in await repo.list_elderly(account.user_id):
        raise HTTPException(status_code=403, detail="未绑定该老人")
    limit = max(1, min(limit, 100))
    records = await ConversationRepo(session).list_emotions(elderly_id, limit)
    return {"user_id": elderly_id, "records": [
        {"emotion": r.emotion, "intensity": r.intensity,
         "created_at": r.created_at.isoformat() if r.created_at else ""}
        for r in records
    ]}


@router.get("/elderly/{elderly_id}/memories")
async def elderly_memories(
    elderly_id: str,
    account: Account = Depends(require_family),
    session: AsyncSession = Depends(get_db),
):
    """家属查看已绑定老人的记忆列表。"""
    repo = FamilyRepo(session)
    if elderly_id not in await repo.list_elderly(account.user_id):
        raise HTTPException(status_code=403, detail="未绑定该老人")
    rows = await MemoryRepo(session).list_all(elderly_id)
    return {"user_id": elderly_id, "memories": [
        {
            "id": r.id,
            "memory_type": r.memory_type,
            "content": r.content,
            "importance": r.importance,
            "created_at": r.created_at.isoformat() if r.created_at else "",
        }
        for r in rows
    ]}


@router.get("/elderly/{elderly_id}/memoir", response_model=MemoirTimeline)
async def elderly_memoir(
    elderly_id: str,
    account: Account = Depends(require_family),
    session: AsyncSession = Depends(get_db),
):
    """家属查看已绑定老人的回忆录（时代轴）。

    契约1/2 的双重保障：
    - 家属**不能**确认/弃用；这里只有读，没有写路径；
    - 服务层只返回 `archived` 且 `visibility ∈ (family, public)` 的条目，
      创伤类 private 故事根本不会出现在响应里（不是前端隐藏）。
    """
    repo = FamilyRepo(session)
    if elderly_id not in await repo.list_elderly(account.user_id):
        raise HTTPException(status_code=403, detail="未绑定该老人")
    return await build_timeline_payload(session, elderly_id, family_view=True)


@router.get("/elderly/{elderly_id}/memoir/compilations",
            response_model=list[CompilationItem])
async def elderly_compilations(
    elderly_id: str,
    account: Account = Depends(require_family),
    session: AsyncSession = Depends(get_db),
):
    """家属列出老人已经排好的短片提示词包。

    契约1：这里**只有读**，没有创建/删除。家属想自己排一条，请让老人在
    老人端操作——编排等于替老人决定"哪些事可以被讲出来"。
    契约2：每条的镜头都按**当下**可见性再过滤一遍；整片被收回则整条不返回
    （对家属等同于不存在），而不是返回一个空壳。
    """
    if elderly_id not in await FamilyRepo(session).list_elderly(account.user_id):
        raise HTTPException(status_code=403, detail="未绑定该老人")

    visible = await visible_story_ids(session, elderly_id)
    items: list[CompilationItem] = []
    for comp in await CompilationRepo(session).list_for_user(elderly_id):
        package = filter_package_for_family(comp.prompt_package, visible)
        if comp.prompt_package and package is None:
            continue
        items.append(compilation_to_dict(comp, package=package))
    return items


@router.get("/elderly/{elderly_id}/memoir/compilations/{comp_id}",
            response_model=CompilationItem)
async def elderly_compilation(
    elderly_id: str,
    comp_id: int,
    account: Account = Depends(require_family),
    session: AsyncSession = Depends(get_db),
):
    """家属读取已生成的提示词包（供复制到外部视频工具）。

    契约1：家属只能**读**，本路由下没有任何创建/删除的写路径。
    契约2：提示词包是编排当时的快照，快照不会自动跟随可见性变化，
    所以在返回前按**当下**的可见故事集合再过滤一次每段镜头——
    老人后来说"这段别给人看"了，家属就不该还能看到那段旁白。
    """
    if elderly_id not in await FamilyRepo(session).list_elderly(account.user_id):
        raise HTTPException(status_code=403, detail="未绑定该老人")

    comp = await CompilationRepo(session).get(comp_id, elderly_id)
    if comp is None:
        raise HTTPException(status_code=404, detail="找不到这段短片")

    visible = {s.id for s in await StoryRepo(session).list_visible_for_family(elderly_id)}
    package = filter_package_for_family(comp.prompt_package, visible)
    if comp.prompt_package and package is None:
        # 整片都被老人收回可见性了 —— 对家属等同于不存在
        raise HTTPException(status_code=404, detail="找不到这段短片")
    return compilation_to_dict(comp, package=package)


# ---------- 家属端回忆照片（M6） ----------
#
# 家属能做的只有两件：给**看得见的**往事补照片、删掉自己补的那张。
# 不能改文字、不能改可见性、不能替老人确认留档（契约1/2/5）。

@router.post("/elderly/{elderly_id}/memoir/stories/{story_id}/media",
             response_model=StoryMediaItem)
async def family_upload_story_photo(
    elderly_id: str,
    story_id: int,
    file: UploadFile = File(...),
    caption: str = Form(""),
    account: Account = Depends(require_family),
    session: AsyncSession = Depends(get_db),
):
    """家属给老人一条**已留档且家属可见**的往事补一张照片。

    三道门：已绑定 → 故事存在 → 故事当下 archived 且 visibility ∈ (family, public)。
    不满足一律 404（不告诉家属"有这条但你看不到"）。
    """
    if elderly_id not in await FamilyRepo(session).list_elderly(account.user_id):
        raise HTTPException(status_code=403, detail="未绑定该老人")

    story = await load_family_story(session, elderly_id, story_id)
    if story is None:
        raise HTTPException(status_code=404, detail="找不到这条回忆")

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
    return media_to_dict(media, elderly_id)


@router.delete("/elderly/{elderly_id}/memoir/media/{media_id}")
async def family_delete_story_photo(
    elderly_id: str,
    media_id: int,
    account: Account = Depends(require_family),
    session: AsyncSession = Depends(get_db),
):
    """家属撤回**自己上传的**照片。

    这里刻意**不**要求故事当前可见：删是让信息变少，不是变多；
    让上传者能收回自己放进去的东西，比"老人改成 private 之后家属连删都删不掉"
    更符合隐私预期。
    """
    if elderly_id not in await FamilyRepo(session).list_elderly(account.user_id):
        raise HTTPException(status_code=403, detail="未绑定该老人")

    media = await StoryMediaRepo(session).get(media_id)
    if media is None or media.uploaded_by != account.user_id:
        raise HTTPException(status_code=404, detail="找不到这张照片")
    story = await StoryRepo(session).get(media.story_id, elderly_id)
    if story is None:
        raise HTTPException(status_code=404, detail="找不到这张照片")

    await detach_photo(session, media)
    await session.commit()
    return {"deleted": True, "id": media_id}


# ---------- 告警 ----------

@router.get("/alerts")
async def list_alerts(
    account: Account = Depends(require_family),
    session: AsyncSession = Depends(get_db),
):
    """家属查看其绑定老人的所有告警。"""
    repo = FamilyRepo(session)
    elderly_ids = await repo.list_elderly(account.user_id)
    if not elderly_ids:
        return []
    alert_repo = AlertRepo(session)
    alerts = []
    for eid in elderly_ids:
        rows = await alert_repo.list_by_elderly(eid, limit=50)
        alerts.extend(rows)
    alerts.sort(key=lambda a: a.created_at, reverse=True)
    return [
        AlertResponse(
            id=a.id,
            elderly_user_id=a.elderly_user_id,
            alert_type=a.alert_type,
            severity=a.severity,
            title=a.title,
            detail=a.detail,
            is_acknowledged=a.is_acknowledged,
            acknowledged_by=a.acknowledged_by,
            acknowledged_at=a.acknowledged_at.isoformat() if a.acknowledged_at else None,
            created_at=a.created_at.isoformat() if a.created_at else "",
        )
        for a in alerts
    ]


@router.post("/alerts/{alert_id}/ack")
async def acknowledge_alert(
    alert_id: int,
    account: Account = Depends(require_family),
    session: AsyncSession = Depends(get_db),
):
    """家属确认告警。"""
    alert_repo = AlertRepo(session)
    ok = await alert_repo.acknowledge(alert_id, account.user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="告警不存在")
    await session.commit()
    return {"status": "ok", "alert_id": alert_id}


# ---------- 家人互动：留言 / 牵挂（双向） ----------

class FamilyMessageCreate(BaseModel):
    content: str
    category: str = "greeting"  # greeting/care/remind/miss


class ElderlyMessageCreate(BaseModel):
    content: str
    category: str = "greeting"
    family_user_id: str


def _msg_to_dict(m: FamilyMessage) -> dict:
    return {
        "id": m.id,
        "family_user_id": m.family_user_id,
        "elderly_user_id": m.elderly_user_id,
        "content": m.content,
        "category": m.category,
        "sender_role": m.sender_role,
        "is_read": m.is_read,
        "reaction": m.reaction,
        "created_at": m.created_at.isoformat() if m.created_at else "",
        "read_at": m.read_at.isoformat() if m.read_at else None,
    }


# ----- 家属侧 -----

@router.post("/elderly/{elderly_id}/messages")
async def send_message(
    elderly_id: str,
    req: FamilyMessageCreate,
    account: Account = Depends(require_family),
    session: AsyncSession = Depends(get_db),
):
    """家属给绑定的老人留一句话。"""
    if elderly_id not in await FamilyRepo(session).list_elderly(account.user_id):
        raise HTTPException(status_code=403, detail="未绑定该老人")
    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")
    content = content[:200]
    mid = await FamilyMessageRepo(session).create(
        account.user_id, elderly_id, content, req.category, sender_role="family"
    )
    await session.commit()
    # 实时推送：通知老人收到新牵挂
    bus.publish(elderly_id, {"type": "family_message", "message_id": mid, "from": "family"})
    return {"id": mid, "status": "ok"}


@router.get("/elderly/{elderly_id}/messages")
async def family_messages(
    elderly_id: str,
    account: Account = Depends(require_family),
    session: AsyncSession = Depends(get_db),
):
    """家属视角：我发给老人的（含已读状态）+ 老人发给我的收件箱。"""
    if elderly_id not in await FamilyRepo(session).list_elderly(account.user_id):
        raise HTTPException(status_code=403, detail="未绑定该老人")
    repo = FamilyMessageRepo(session)
    sent = await repo.list_sent_by_family(account.user_id, elderly_id)
    inbox = await repo.list_received_by_family(account.user_id, elderly_id)
    return {
        "sent": [_msg_to_dict(m) for m in sent],
        "inbox": [_msg_to_dict(m) for m in inbox],
    }


# ----- 老人侧 -----

@router.get("/my-families")
async def my_families(
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    """老人查看绑定自己的家属列表（用于选择留言对象）。"""
    from sqlalchemy import select

    from app.db.models import FamilyElderlyBinding

    rows = (await session.execute(
        select(FamilyElderlyBinding).where(
            FamilyElderlyBinding.elderly_user_id == account.user_id
        )
    )).scalars().all()
    return {
        "families": [
            {
                "family_user_id": r.family_user_id,
                "relationship_name": r.relationship_name,
            }
            for r in rows
        ]
    }


@router.post("/messages")
async def elderly_send_message(
    req: ElderlyMessageCreate,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    """老人给某位家人留言。"""
    from sqlalchemy import select

    from app.db.models import FamilyElderlyBinding

    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")
    content = content[:200]
    binding = (await session.execute(
        select(FamilyElderlyBinding).where(
            FamilyElderlyBinding.elderly_user_id == account.user_id,
            FamilyElderlyBinding.family_user_id == req.family_user_id,
        )
    )).scalar_one_or_none()
    if binding is None:
        raise HTTPException(status_code=403, detail="未找到该家属")
    mid = await FamilyMessageRepo(session).create(
        req.family_user_id, account.user_id, content, req.category, sender_role="elderly"
    )
    await session.commit()
    # 实时推送：通知家属收到老人留言
    bus.publish(
        req.family_user_id,
        {"type": "family_message", "message_id": mid, "from": "elderly"},
    )
    return {"id": mid, "status": "ok"}


@router.get("/messages")
async def elderly_messages(
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    """老人视角：家人发给我的收件箱 + 我发出的留言 + 未读数。

    日报推送（category=digest）是系统以老人名义生成给家属的，不属于老人留言，
    从老人的「我发出的」列表中过滤掉。
    """
    repo = FamilyMessageRepo(session)
    inbox = await repo.list_for_elderly(account.user_id)
    sent = await repo.list_sent_by_elderly(account.user_id)
    unread = await repo.unread_for_elderly(account.user_id)
    return {
        "unread": unread,
        "inbox": [_msg_to_dict(m) for m in inbox],
        "sent": [_msg_to_dict(m) for m in sent if m.category != "digest"],
    }


# ----- 双方共用：标记已读 + 回应 -----

@router.post("/messages/{message_id}/read")
async def read_message(
    message_id: int,
    reaction: Optional[str] = None,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
):
    """接收方标记已读，并可回一个表情（如 ❤️）。"""
    msg = await FamilyMessageRepo(session).mark_read(
        message_id, account.user_id, reaction
    )
    if msg is None:
        raise HTTPException(status_code=404, detail="留言不存在")
    await session.commit()
    # 实时推送：通知发送方「对方已读 / 回应」
    sender = msg.family_user_id if msg.sender_role == "family" else msg.elderly_user_id
    bus.publish(
        sender,
        {"type": "family_message_read", "message_id": message_id, "reaction": reaction},
    )
    return {"status": "ok", "message_id": message_id, "reaction": reaction}
