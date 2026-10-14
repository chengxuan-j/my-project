"""家属看板：绑定老人 + 查看老人情绪历史 + 查看老人记忆 + 告警管理 + 家人留言互动。"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.dependencies import get_current_account, require_elderly, require_family
from app.core.events import bus
from app.db.base import get_db
from app.db.models import Account, FamilyMessage
from app.repositories.account_repo import AccountRepo
from app.repositories.alert_repo import AlertRepo
from app.repositories.family_message_repo import FamilyMessageRepo
from app.repositories.profile_repo import ConversationRepo, FamilyRepo, MemoryRepo
from app.schemas import AlertResponse, BindElderlyRequest
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
