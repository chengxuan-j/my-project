"""机器狗实时动作控制：由前端视觉引擎直接驱动。"""
import logging
from datetime import datetime
from typing import List

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.dependencies import get_current_account, require_elderly, require_family
from app.core.events import bus
from app.db.base import get_db
from app.db.models import Account
from app.repositories.family_message_repo import FamilyMessageRepo
from app.repositories.profile_repo import FamilyRepo
from app.services.dog_control import KEY_MAP, execute_actions, execute_stop

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dog", tags=["机器狗"])


class DogActionRequest(BaseModel):
    action_key: str = Field(..., description="动作标识，和 vision-control Action.key 对齐")
    duration: float | None = Field(None, description="move 类动作持续时长（秒），默认 1.5，最大 3.0")


class DogActionResponse(BaseModel):
    success: bool
    action_key: str
    action_name: str
    dog_reached: bool
    message: str


VALID_KEYS = set(KEY_MAP.keys())


async def push_to_dog(text: str) -> bool:
    """把一句话推给当前已连接小智服务端的机器狗，让它开口念出来。

    返回 True 表示已成功下发朗读任务（不代表狗一定播放成功）。
    狗未连接 / 小智服务不可达时静默失败，不影响主流程（SSE 仍会推老人端 TTS）。
    """
    settings = get_settings()
    # 从视觉地址推导出小智 HTTP 基址：http://127.0.0.1:8003/mcp/... -> http://127.0.0.1:8003
    base = settings.xiaozhi_vision_url.split("/mcp", 1)[0].rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{base}/devices")
            if r.status_code != 200:
                return False
            devices = (r.json() or {}).get("online_devices") or []
            if not devices:
                logger.info("push_to_dog: 当前没有已连接的狗设备，跳过发声")
                return False
            dev = devices[0]
            resp = await client.post(
                f"{base}/devices/{dev}/say",
                json={"text": text},
            )
            ok = resp.status_code == 200
            logger.info("push_to_dog -> device=%s ok=%s", dev, ok)
            return ok
    except Exception as e:  # noqa: BLE001
        logger.warning("push_to_dog 失败（狗未连或不可达）: %s", e)
        return False



@router.post("/action", response_model=DogActionResponse)
async def dog_action(
    body: DogActionRequest,
    account: Account = Depends(get_current_account),
):
    if body.action_key not in VALID_KEYS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的动作 '{body.action_key}'。可用：{', '.join(VALID_KEYS)}",
        )
    settings = get_settings()
    if body.action_key == "stop":
        dog_reached = await execute_stop(settings.dog_base_url)
        name = "停止"
    else:
        name = KEY_MAP[body.action_key]
        seq = [(name, body.duration)]
        dog_reached = await execute_actions(settings.dog_base_url, seq)
    msg = (
        f"小狗已执行『{name}』"
        if dog_reached
        else f"小狗想给您表演『{name}』，但它现在不在线"
    )
    logger.info("dog_action: key=%s name=%s reached=%s", body.action_key, name, dog_reached)
    return DogActionResponse(
        success=True,
        action_key=body.action_key,
        action_name=name,
        dog_reached=dog_reached,
        message=msg,
    )


@router.get("/actions", response_model=List[dict])
async def list_actions(account: Account = Depends(get_current_account)):
    """返回前端视觉引擎支持的所有动作及其触发姿势说明。"""
    cheat_sheet = [
        {"key": "walk_forward", "name": "前进", "hint": "双手高举过头"},
        {"key": "turn_left", "name": "左转", "hint": "只举左手"},
        {"key": "turn_right", "name": "右转", "hint": "只举右手"},
        {"key": "sit", "name": "鞠躬", "hint": "双手抱头 / 下蹲"},
        {"key": "stand", "name": "握手", "hint": "张开手掌"},
        {"key": "stretch", "name": "伸懒腰", "hint": "竖大拇指"},
        {"key": "shake", "name": "摇摆", "hint": "剪刀手"},
    ]
    return cheat_sheet


class DogRelayRequest(BaseModel):
    elderly_user_id: str = Field(..., description="要传话给哪位老人（必须是该家属已绑定的）")
    relation: str = Field(..., description="家属与老人的关系，如 女儿 / 儿子 / 孙女")
    content: str = Field(..., description="要传的话的内容", max_length=100)


class DogRelayResponse(BaseModel):
    status: str
    text: str
    message: str


@router.post("/relay", response_model=DogRelayResponse)
async def dog_relay(
    body: DogRelayRequest,
    account: Account = Depends(require_family),
    session: AsyncSession = Depends(get_db),
):
    """家属让小狗给老人「传话」（家属端不指挥动作，仅传话）。

    后台把关系与内容合成一句话，如「女儿提醒您：记得按时吃药」，
    通过事件总线实时推送到老人端，由老人端的小狗形象用 TTS 念出来。
    """
    if body.elderly_user_id not in await FamilyRepo(session).list_elderly(account.user_id):
        raise HTTPException(status_code=403, detail="未绑定该老人，无法传话")

    relation = body.relation.strip()
    content = body.content.strip()
    if not relation or not content:
        raise HTTPException(status_code=400, detail="关系和传话内容均不能为空")

    # 关系称呼后加「提醒您：」，读起来自然
    spoken = f"{relation}提醒您：{content}"

    # 落库：复用 family_messages 表，用 category='dog_relay' 标记为「待小狗传话」。
    # 老人端当时不在线也没关系，登录后通过 GET /dog/relays 补播一次。
    relay_id = await FamilyMessageRepo(session).create(
        account.user_id,
        body.elderly_user_id,
        spoken,
        category="dog_relay",
        sender_role="family",
    )
    await session.commit()

    # 若机器狗已连到小智服务端，先尝试让它开口念这句话（家属端只传话、不指挥动作）
    dog_spoke = await push_to_dog(spoken)

    # 实时推送（若老人端已连 SSE，立刻念出来；若狗已开口，前端可跳过浏览器 TTS）
    bus.publish(
        body.elderly_user_id,
        {
            "type": "dog_relay",
            "text": spoken,
            "relation": relation,
            "content": content,
            "message_id": relay_id,
            "dog_spoke": dog_spoke,
            "created_at": datetime.now().isoformat(),
        },
    )

    logger.info(
        "dog_relay: %s -> %s | %s (id=%s, dog_spoke=%s)",
        account.user_id, body.elderly_user_id, spoken, relay_id, dog_spoke,
    )
    msg = f"已让小狗把「{spoken}」带给{relation}"
    if dog_spoke:
        msg += "，小狗正在说话"
    return DogRelayResponse(
        status="ok",
        text=spoken,
        message=msg,
    )


@router.get("/relays")
async def pending_relays(
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    """老人端拉取未送达的小狗传话（上线补播）。

    取出即标记已读，避免每次刷新都重复播报同一句话。
    """
    repo = FamilyMessageRepo(session)
    rows = await repo.list_pending_dog_relays(account.user_id)
    out = []
    for m in rows:
        await repo.mark_read(m.id, account.user_id)
        # 若狗在线，补播时也直接让它开口（避免只念在浏览器里）
        dog_spoke = await push_to_dog(m.content)
        out.append(
            {
                "id": m.id,
                "text": m.content,
                "dog_spoke": dog_spoke,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
        )
    if rows:
        await session.commit()
        logger.info("dog_relay replay: user=%s count=%d", account.user_id, len(rows))
    return {"relays": out}
