"""聊天路由（带 JWT 认证）。user_id 从 token 取，不再接受客户端传入。"""
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.agent.companion_agent import run as run_agent
from app.core.container import (
    get_conversation_summarizer,
    get_memory_extractor,
    get_memory_manager,
)
from app.core.dependencies import get_current_account
from app.db.models import Account
from app.llm.qwen_client import LLMError
from app.memory.conversation_summarizer import ConversationSummarizer
from app.memory.memory_extractor import MemoryExtractor
from app.memory.memory_manager import MemoryManager
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


@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    background: BackgroundTasks,
    account: Account = Depends(get_current_account),
    memory: MemoryManager = Depends(get_memory_manager),
    extractor: MemoryExtractor = Depends(get_memory_extractor),
    summarizer: ConversationSummarizer = Depends(get_conversation_summarizer),
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

    if ctx["risk_level"] != "high":
        background.add_task(_extract_and_save, memory, extractor, user_id, msg, reply)

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
