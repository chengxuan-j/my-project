"""API 路由（旧版，无认证）。

⚠️ 已弃用（Deprecated）：本模块为旧版根路径路由（/chat、/profile/...，无认证），
仅用于向后兼容 demo 与测试基线（tests/test_chat.py）。
新代码请统一使用带 JWT 的 /api/v1/* 路由（见 app/api/v1/）。

Agent 化后：POST /chat 由 LangGraph 图（app.agent.companion_agent）编排，
流程 = 情境分析 → 上下文（画像/记忆/策略/推荐）→ 回复生成 → 后台记忆提取。
语音：POST /speech/tts（文字→语音URL）、
     POST /speech/asr/submit（上传音频→返回 task_id）、
     GET /speech/asr/{task_id}（查询转写结果）。
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File
from pydantic import BaseModel, Field

from app.agent.companion_agent import run as run_agent
from app.content import games, music, stories
from app.db import get_conn
from app.llm.qwen_client import LLMError, QwenClient
from app.memory.memory_extractor import MemoryExtractor
from app.memory.memory_manager import MemoryManager
from app.speech.speech_client import (
    ASR_PENDING,
    SpeechError,
    _client as speech_client,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_client = QwenClient()
_memory = MemoryManager()
_extractor = MemoryExtractor(_client)


class ChatRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=64,
                         pattern=r"^[A-Za-z0-9_\-\u4e00-\u9fff]+$")
    message: str = Field(..., min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    reply: str
    user_id: str
    name: str = ""
    emotion: str = "neutral"
    emotion_intensity: float = 0.0
    intent: str = "casual_chat"
    scene: str = "conversation"
    topic: str = ""
    need: str = "none"
    risk_level: str = "low"
    action: str = ""                            # 第 5 轮：陪伴策略动作
    action_reason: str = ""                     # 决策理由（可解释性）
    recommendation: Optional[Dict[str, Any]] = None  # 第 6 轮：推荐内容（音乐/故事）
    degraded: bool = False                       # 情境分析是否走了 fallback
    recalled_memories: List[str] = Field(default_factory=list)


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "model": _client.model,
        "api_configured": _client.is_configured,
    }


async def _extract_and_save_memories(user_id: str, user_msg: str,
                                      ai_reply: str) -> None:
    """后台任务③：回复已返回后再跑记忆提取，不增加用户等待。失败静默。"""
    try:
        memories = await _extractor.extract(user_msg, ai_reply)
        if memories:
            await _memory.save_extracted_memories(user_id, memories)
    except Exception:
        logger.exception("后台长期记忆提取异常 user_id=%s", user_id)


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, background: BackgroundTasks):
    msg = req.message.strip()
    if not msg:
        raise HTTPException(status_code=400, detail="消息不能为空")

    # 执行 Agent 图（分析 → 上下文 → 生成）；生成失败抛 LLMError
    try:
        result = await run_agent(req.user_id, msg)
    except LLMError as e:
        logger.error("Agent 执行失败: %s", e)
        raise HTTPException(status_code=502, detail=str(e))

    ctx = result["context"]
    analysis = result["analysis"]
    reply = result["reply"]

    # 落库（对话 + 情绪历史）
    _ctx_obj = ctx["_ctx"]
    _memory.save_turn(req.user_id, _ctx_obj, msg, reply)

    # 后台长期记忆提取；高风险内容不提取，避免记录危机语句
    if ctx["risk_level"] != "high":
        background.add_task(_extract_and_save_memories, req.user_id, msg, reply)

    return ChatResponse(
        reply=reply,
        user_id=req.user_id,
        name=ctx["profile"]["name"],
        emotion=ctx["emotion"],
        emotion_intensity=round(ctx["emotion_intensity"], 2),
        intent=ctx["intent"],
        scene=ctx["scene"],
        topic=ctx["topic"],
        need=ctx["need"],
        risk_level=ctx["risk_level"],
        action=ctx["action"],
        action_reason=ctx["action_reason"],
        recommendation=ctx["recommendation"],
        degraded=bool(analysis.get("degraded")),
        recalled_memories=[m["content"] for m in ctx["long_memories"]],
    )


@router.get("/emotion/{user_id}")
async def emotion_history(user_id: str, limit: int = 20):
    """情绪历史（emotion_records 表），用于观察情绪趋势。"""
    limit = max(1, min(limit, 100))
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT emotion, intensity, created_at FROM emotion_records
               WHERE user_id = ? ORDER BY id DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
    return {"user_id": user_id, "records": [dict(r) for r in rows]}


@router.get("/profile/{user_id}")
async def get_profile(user_id: str):
    try:
        return _memory.profiles.get(user_id).model_dump()
    except Exception as e:  # sqlite3.Error 等
        logger.exception("读取画像失败")
        raise HTTPException(status_code=500, detail=f"读取画像失败: {e}")


@router.put("/profile/{user_id}")
async def put_profile(user_id: str, patch: Dict[str, Any]):
    """局部更新画像字段（如 {"interests": ["京剧"]}）。"""
    try:
        return _memory.profiles.update_partial(user_id, patch).model_dump()
    except Exception as e:
        logger.exception("更新画像失败")
        raise HTTPException(status_code=400, detail=f"更新画像失败: {e}")


@router.get("/memory/{user_id}/state")
async def memory_state(user_id: str):
    """查看短期记忆：当前状态 + 最近对话。"""
    state = _memory.short.current_state(user_id)
    recent = _memory.short.recent_messages(user_id, turns=10)
    return {
        "state": state,
        "recent": [{"role": r, "content": c} for r, c in recent],
    }


@router.get("/memories/{user_id}")
async def list_memories(user_id: str):
    """列出该老人的全部长期记忆（按 importance 降序）。"""
    return {"user_id": user_id, "memories": _memory.long.list_all(user_id)}


@router.delete("/memories/{user_id}/{memory_id}")
async def delete_memory(user_id: str, memory_id: int):
    ok = _memory.long.delete(user_id, memory_id)
    if not ok:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return {"deleted": True, "id": memory_id}


# ---------- 第 6 轮：推荐与游戏（本地数据/规则，不依赖 Qwen） ----------

class RecommendRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=64,
                         pattern=r"^[A-Za-z0-9_\-\u4e00-\u9fff]+$")


@router.post("/recommend/music")
async def recommend_music(req: RecommendRequest):
    """根据画像 + 当前情绪 + 场景推荐音乐。"""
    profile = _memory.profiles.get(req.user_id)
    state = _memory.short.current_state(req.user_id)
    items = music.recommend(profile, state["emotion"], state["scene"])
    return {"user_id": req.user_id, "emotion": state["emotion"],
            "scene": state["scene"], "items": items}


@router.post("/recommend/story")
async def recommend_story(req: RecommendRequest):
    """按情绪/兴趣推荐故事。"""
    profile = _memory.profiles.get(req.user_id)
    state = _memory.short.current_state(req.user_id)
    items = stories.recommend(profile, state["emotion"])
    return {"user_id": req.user_id, "emotion": state["emotion"], "items": items}


class GameNewRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=64,
                         pattern=r"^[A-Za-z0-9_\-\u4e00-\u9fff]+$")
    game: str = "arithmetic"   # number_memory / idiom_chain / arithmetic
    difficulty: str = "easy"


class GameCheckRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=64,
                         pattern=r"^[A-Za-z0-9_\-\u4e00-\u9fff]+$")
    game: str = "arithmetic"
    answer: str = ""
    # 数字记忆 / 算术 / 成语接龙校验所需上下文
    sequence: str = ""
    expected: int = 0
    start: str = ""


@router.post("/game/new")
async def game_new(req: GameNewRequest):
    """开局一个益智游戏。本地规则出题，成语接龙在 Qwen 可用时用其生成。"""
    if req.game == "number_memory":
        return games.number_memory_new()
    if req.game == "arithmetic":
        return games.arithmetic_new(req.difficulty)
    if req.game == "idiom_chain":
        return await games.idiom_chain_start(_client if _client.is_configured else None)
    raise HTTPException(status_code=400, detail="未知游戏类型")


@router.post("/game/check")
async def game_check(req: GameCheckRequest):
    """判题。"""
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


# ---------- 语音：TTS + ASR（远程 API，零本地模型） ----------

class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    voice: str = "longanhuan_v3.6"


class TTSResponse(BaseModel):
    audio_url: str


class ASRSubmitResponse(BaseModel):
    task_id: str
    status: str = "PENDING"


class ASRResultResponse(BaseModel):
    task_id: str
    status: str
    text: Optional[str] = None
    error: Optional[str] = None


@router.post("/speech/tts", response_model=TTSResponse)
async def speech_tts(req: TTSRequest):
    """文字 → 语音。返回可播放的音频 URL（24 小时有效）。"""
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="文本不能为空")
    try:
        url = await speech_client.synthesize(text, voice=req.voice)
    except SpeechError as e:
        logger.error("TTS 失败: %s", e)
        raise HTTPException(status_code=502, detail=str(e))
    return TTSResponse(audio_url=url)


@router.post("/speech/asr/submit", response_model=ASRSubmitResponse)
async def speech_asr_submit(file: UploadFile = File(...)):
    """音频 → 转写任务。上传 wav/mp3，立即返回 task_id；客户端再轮询结果。

    非阻塞：上传与提交任务共耗时几秒，识别由 DashScope 异步处理。
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="音频为空")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="音频超过 10MB")
    try:
        oss_url = await speech_client.upload_audio(
            data, filename=file.filename or "audio.wav"
        )
        task_id = await speech_client.submit_transcription(oss_url)
    except SpeechError as e:
        logger.error("ASR 提交失败: %s", e)
        raise HTTPException(status_code=502, detail=str(e))
    logger.info("ASR 已提交 task_id=%s", task_id)
    return ASRSubmitResponse(task_id=task_id, status=ASR_PENDING)


@router.get("/speech/asr/{task_id}", response_model=ASRResultResponse)
async def speech_asr_result(task_id: str):
    """查询转写任务结果（非阻塞，单次查询）。

    status ∈ {PENDING, RUNNING, SUCCEEDED, FAILED, CANCELED}
    SUCCEEDED 时 text 非空；FAILED/CANCELED 时 error 非空。
    前端建议每 1~2 秒轮询，直到 SUCCEEDED/FAILED/CANCELED。
    """
    try:
        res = await speech_client.fetch_result(task_id)
    except SpeechError as e:
        logger.error("ASR 查询失败 task_id=%s: %s", task_id, e)
        raise HTTPException(status_code=502, detail=str(e))
    return ASRResultResponse(
        task_id=task_id,
        status=res["status"],
        text=res["text"],
        error=res["error"],
    )
