"""LangGraph Agent 编排：把陪伴流程重构成状态图 + 工具。

设计文档第一阶段原本"不做 Agent"，此处是项目完成后的架构升级：
- 用 LangGraph StateGraph 编排各阶段（分析 → 画像/记忆 → 策略 → 生成）
- 每个阶段封装为可独立调用的「工具」（LangChain @tool），便于测试、复用、观察
- 保持 /chat 响应契约不变，路由层无感知

状态流转：
    START → analyze → context → generate → END
"""
import logging
from typing import Any, Dict, List, Optional, TypedDict

from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph

from app.companion.companion_policy import CompanionPolicy
from app.companion.prompts import build_messages
from app.emotion.emotion_analyzer import AnalysisResult, EmotionAnalyzer
from app.llm.qwen_client import QwenClient
from app.memory.memory_manager import MemoryManager

logger = logging.getLogger(__name__)

# 回复长度硬上限：约 80 中文字。老人看不了长篇，且生成耗时与长度成正比，
# 这是整个链路最大的提速点（实测 277 字 → 80 字，生成耗时降 3 倍以上）
MAX_REPLY_TOKENS = 150


class AgentState(TypedDict, total=False):
    user_id: str
    message: str
    analysis: Dict[str, Any]          # 情境分析结构化结果
    context: Dict[str, Any]           # 画像/记忆/策略/推荐聚合
    reply: str                        # 最终回复


# ---------------------------------------------------------------------------
# 依赖（模块级单例，测试可通过 reset_dependencies 注入 mock）
# ---------------------------------------------------------------------------

class _Deps:
    client: QwenClient
    analyzer: EmotionAnalyzer
    memory: MemoryManager
    policy: CompanionPolicy

    def __init__(self) -> None:
        self.client = QwenClient()
        self.analyzer = EmotionAnalyzer(self.client)
        self.memory = MemoryManager()
        self.policy = CompanionPolicy()


_deps = _Deps()


def reset_dependencies(deps: Optional[_Deps] = None) -> None:
    """测试注入用：替换模块级依赖。"""
    global _deps
    _deps = deps if deps is not None else _Deps()


# ---------------------------------------------------------------------------
# 工具层：每个工具做一件事，输入输出明确
# ---------------------------------------------------------------------------

@tool
async def analyze_situation(user_id: str, message: str) -> Dict[str, Any]:
    """情境分析工具：识别老人当前情绪、意图、场景、需求与风险。"""
    history = _deps.memory.short.recent_messages(user_id)
    result: AnalysisResult = await _deps.analyzer.analyze(message, recent=history)
    return result.to_dict()


@tool
async def build_context(user_id: str, message: str,
                        analysis: Dict[str, Any]) -> Dict[str, Any]:
    """上下文工具：画像 + 短期/长期记忆 + 策略决策 + 内容推荐。"""
    a = AnalysisResult(**analysis)
    ctx = await _deps.memory.build_context(user_id, message, analysis=a)
    return {
        "profile": ctx.profile.model_dump(),
        "emotion": ctx.emotion,
        "emotion_intensity": ctx.emotion_intensity,
        "intent": ctx.intent,
        "scene": ctx.scene,
        "topic": ctx.current_topic,
        "need": ctx.need,
        "risk_level": ctx.risk_level,
        "action": ctx.decision.action if ctx.decision else "",
        "action_reason": ctx.decision.reason if ctx.decision else "",
        "response_style": ctx.decision.response_style if ctx.decision else "",
        "recommendation": ctx.recommendation,
        "long_memories": ctx.long_memories,
        "knowledge_results": ctx.knowledge_results,
        "safety_directive": ctx.safety_directive,
        "_ctx": ctx,  # 内部对象，供 generate 工具直接复用
    }


@tool
async def generate_reply(user_id: str, message: str,
                         context: Dict[str, Any]) -> str:
    """回复生成工具：注入画像+记忆+情境+策略，调用 Qwen 生成。"""
    ctx = context["_ctx"]
    messages = build_messages(ctx, message)
    # DEBUG: 打印画像和 system prompt 关键部分
    logger.info("[DEBUG] user_id=%s, profile_name=%s, prompt_block=%s",
                user_id, ctx.profile.name, ctx.profile.prompt_block())
    logger.info("[DEBUG] system_prompt (first 800 chars): %s",
                messages[0]["content"][:800])
    temperature = 0.5 if ctx.risk_level == "high" else 0.8
    # max_tokens 硬上限：老人陪伴回复本就该简短，同时显著缩短生成耗时
    return await _deps.client.chat(messages, temperature=temperature,
                                   max_tokens=MAX_REPLY_TOKENS)


# ---------------------------------------------------------------------------
# 图节点
# ---------------------------------------------------------------------------

async def _analyze_node(state: AgentState) -> Dict[str, Any]:
    return {"analysis": await analyze_situation.ainvoke({
        "user_id": state["user_id"], "message": state["message"],
    })}


async def _context_node(state: AgentState) -> Dict[str, Any]:
    return {"context": await build_context.ainvoke({
        "user_id": state["user_id"], "message": state["message"],
        "analysis": state["analysis"],
    })}


async def _generate_node(state: AgentState) -> Dict[str, Any]:
    return {"reply": await generate_reply.ainvoke({
        "user_id": state["user_id"], "message": state["message"],
        "context": state["context"],
    })}


def _build_graph():
    g = StateGraph(AgentState)
    g.add_node("analyze", _analyze_node)
    g.add_node("context", _context_node)
    g.add_node("generate", _generate_node)
    g.add_edge(START, "analyze")
    g.add_edge("analyze", "context")
    g.add_edge("context", "generate")
    g.add_edge("generate", END)
    return g.compile()


graph = _build_graph()


async def run(user_id: str, message: str) -> Dict[str, Any]:
    """执行整条 Agent 图，返回 {reply, analysis, context}。"""
    result = await graph.ainvoke({"user_id": user_id, "message": message})
    return {
        "reply": result.get("reply", ""),
        "analysis": result.get("analysis", {}),
        "context": result.get("context", {}),
    }
