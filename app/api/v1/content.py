"""推荐与游戏（本地数据/规则，不依赖 Qwen）。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.content import games, music, stories
from app.core.container import get_memory_manager, get_qwen_client
from app.core.dependencies import get_current_account
from app.db.models import Account
from app.llm.qwen_client import QwenClient
from app.memory.memory_manager import MemoryManager

router = APIRouter(tags=["content"])


@router.post("/recommend/music")
async def recommend_music(
    limit: int = 3,
    account: Account = Depends(get_current_account),
    memory: MemoryManager = Depends(get_memory_manager),
):
    limit = max(1, min(limit, 10))
    profile = memory.profiles.get(account.user_id)
    state = memory.short.current_state(account.user_id)
    items = music.recommend(profile, state["emotion"], state["scene"], limit=limit)
    return {"user_id": account.user_id, "emotion": state["emotion"],
            "scene": state["scene"], "items": items}


@router.post("/recommend/story")
async def recommend_story(
    limit: int = 3,
    account: Account = Depends(get_current_account),
    memory: MemoryManager = Depends(get_memory_manager),
):
    limit = max(1, min(limit, 10))
    profile = memory.profiles.get(account.user_id)
    state = memory.short.current_state(account.user_id)
    items = stories.recommend(profile, state["emotion"], limit=limit)
    return {"user_id": account.user_id, "emotion": state["emotion"], "items": items}


class GameNewRequest(BaseModel):
    game: str = "arithmetic"          # number_memory / idiom_chain / arithmetic
    difficulty: str = "easy"


class GameCheckRequest(BaseModel):
    game: str = "arithmetic"
    answer: str = ""
    sequence: str = ""
    expected: int = 0
    start: str = ""


@router.post("/game/new")
async def game_new(
    req: GameNewRequest,
    client: QwenClient = Depends(get_qwen_client),
):
    if req.game == "number_memory":
        return games.number_memory_new()
    if req.game == "arithmetic":
        return games.arithmetic_new(req.difficulty)
    if req.game == "idiom_chain":
        return await games.idiom_chain_start(
            client if client.is_configured else None
        )
    raise HTTPException(status_code=400, detail="未知游戏类型")


@router.post("/game/check")
async def game_check(req: GameCheckRequest):
    if req.game == "number_memory":
        if not req.sequence:
            raise HTTPException(status_code=400, detail="缺少 sequence")
        return games.number_memory_check(req.sequence, req.answer)
    if req.game == "arithmetic":
        return games.arithmetic_check(req.expected, req.answer)
    if req.game == "idiom_chain":
        if not req.start:
            raise HTTPException(status_code=400, detail="缺少 start")
        return games.idiom_chain_check(req.start, req.answer)
    raise HTTPException(status_code=400, detail="未知游戏类型")
