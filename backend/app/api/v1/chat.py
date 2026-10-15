"""聊天路由（带 JWT 认证）。user_id 从 token 取，不再接受客户端传入。"""
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.agent.companion_agent import run as run_agent
from app.config import get_settings
from app.core.container import (
    get_conversation_summarizer,
    get_memory_extractor,
    get_memory_manager,
    get_story_extractor,
)
from app.core.dependencies import get_current_account
from app.db.base import get_session_factory
from app.db.models import Account
from app.llm.qwen_client import LLMError
from app.memory.conversation_summarizer import ConversationSummarizer
from app.memory.memory_extractor import MemoryExtractor
from app.memory.memory_manager import MemoryManager
from app.memoir import elicitation, story_service
from app.memoir.story_extractor import StoryExtractor
from app.schemas import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


async def _extract_and_save(
    memory: MemoryManager,
    extractor: MemoryExtractor,
    user_id: str,
    user_msg: str,
    ai_reply: str,
) -> None:
    try:
        memories = await extractor.extract(user_msg, ai_reply)
        if memories:
            await memory.save_extracted_memories(user_id, memories)
    except Exception:
        logger.exception("后台记忆提取异常 user_id=%s", user_id)


async def _compress_conversation(
    memory: MemoryManager,
    summarizer: ConversationSummarizer,
    user_id: str,
) -> None:
    """后台任务：压缩对话历史。"""
    try:
        old_turns = memory.short.get_old_turns(user_id)
        if not old_turns:
            return
        summary = await summarizer.summarize(old_turns)
        if summary:
            memory.short.compress_old_turns(user_id, summary)
            logger.info("对话压缩完成 user_id=%s", user_id)
    except Exception:
        logger.exception("对话压缩异常 user_id=%s", user_id)


async def _extract_and_save_story(
    extractor: StoryExtractor,
    user_id: str,
    user_msg: str,
    ai_reply: str,
) -> None:
    """后台任务：生平故事提取 + 落库（回忆录管线，与事实记忆完全独立）。

    - 与 `_extract_and_save` 共用同一套调度模式（后台、异步、失败静默）；
    - 只写 life_stories / story_elicitation_queue，不碰 memories；
    - LLM 不可用 → 静默返回，绝不影响 /chat 主流程。
    """
    try:
        extraction = await extractor.extract(user_msg, ai_reply)
        if not extraction:
            return
        async with get_session_factory()() as session:
            await story_service.ingest(session, user_id, extraction, user_msg, ai_reply)
            await session.commit()
    except Exception:
        logger.exception("后台生平故事提取异常 user_id=%s", user_id)


async def _finalize_memoir(
    user_id: str,
    user_msg: str,
    elicitation_decision: dict | None,
    cooldown_days: int,
) -> None:
    """生成成功后的回忆录收尾（回避处理 + 追问记账）。

    **刻意放在请求内同步执行**，不用后台任务：
    - 回避处理一落盘就是 private + 锁定（契约2），晚一步都算失守；
    - 追问记账是「每会话 ≤1 问」硬上限的账本（契约3），放后台的话
      老人连发两条消息就可能被问两次——那正是这个上限要防的事。
    代价是几毫秒，换契约确定性，划算。失败只记日志，绝不影响已发出的回复。
    """
    try:
        decision = (
            elicitation.ElicitationDecision(**elicitation_decision)
            if elicitation_decision else None
        )
        await elicitation.finalize_turn(
            user_id, user_msg, decision, cooldown_days=cooldown_days
        )
    except Exception:
        logger.exception("回忆录收尾异常 user_id=%s", user_id)


@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    background: BackgroundTasks,
    account: Account = Depends(get_current_account),
    memory: MemoryManager = Depends(get_memory_manager),
    extractor: MemoryExtractor = Depends(get_memory_extractor),
    summarizer: ConversationSummarizer = Depends(get_conversation_summarizer),
    story_extractor: StoryExtractor = Depends(get_story_extractor),
):
    msg = req.message.strip()
    if not msg:
        raise HTTPException(status_code=400, detail="消息不能为空")

    # user_id 从 token 取，不可伪造
    user_id = account.user_id

    try:
        result = await run_agent(user_id, msg)
    except LLMError as e:
        logger.error("Agent 执行失败: %s", e)
        raise HTTPException(status_code=502, detail=str(e))

    ctx = result["context"]
    analysis = result["analysis"]
    reply = result["reply"]

    memory.save_turn(user_id, ctx["_ctx"], msg, reply)

    # M4：回忆录收尾（同步做，见 _finalize_memoir 的说明）。
    # 只在这轮真有问题要问、或老人明确表示不想谈时才付这份开销。
    settings = get_settings()
    if settings.memoir_enabled:
        pending_decision = ctx.get("elicitation")
        if pending_decision or elicitation.detect_avoidance(msg):
            await _finalize_memoir(
                user_id, msg, pending_decision, settings.memoir_gap_cooldown_days
            )

    if ctx["risk_level"] != "high":
        background.add_task(_extract_and_save, memory, extractor, user_id, msg, reply)
        # 回忆录：生平故事提取（暗发布，MEMOIR_ENABLED=true 才启用）
        if settings.memoir_enabled:
            background.add_task(_extract_and_save_story, story_extractor, user_id, msg, reply)

    # 检查是否需要压缩对话历史
    if memory.should_compress_conversation(user_id):
        background.add_task(_compress_conversation, memory, summarizer, user_id)

    # 生成 recommendation_id 供前端提交反馈
    recommendation_id = None
    if ctx["recommendation"]:
        recommendation_id = str(uuid.uuid4())

    return ChatResponse(
        reply=reply,
        user_id=user_id,
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
        recommendation_id=recommendation_id,
        degraded=bool(analysis.get("degraded")),
        recalled_memories=[m["content"] for m in ctx["long_memories"]],
        knowledge_sources=[
            {
                "document_id": item["document_id"],
                "title": item["title"],
                "source": item.get("source", ""),
                "score": item["score"],
            }
            for item in ctx.get("knowledge_results", [])
        ],
    )
