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
from app.companion.prompts import (
    LENGTH_RULE_DEFAULT,
    LENGTH_RULE_LONG,
    LENGTH_RULE_SHORT,
    build_messages,
)
from app.emotion.emotion_analyzer import AnalysisResult, EmotionAnalyzer
from app.llm.qwen_client import QwenClient
from app.memory.memory_manager import MemoryManager
from app.services.face_emotion import face_emotion

logger = logging.getLogger(__name__)

# 回复长度分档（token 数，中文约 1 token ≈ 0.5 字）。
# 老人陪伴场景：功能性回应要干脆，往事/故事要能展开。
REPLY_TOKENS_SHORT = 80    # 约 40~50 字：寒暄、提醒、执行类、危机干预
REPLY_TOKENS_MEDIUM = 150  # 约 80 字：日常对话（原固定值）
REPLY_TOKENS_LONG = 240    # 约 130~150 字：讲故事、接往事、回忆追问

# 功能性强、要干脆的意图：说完就完，不展开
_SHORT_INTENTS = {"greeting", "reminder", "safety_alert",
                  "music_request", "game_request"}
# 需要展开的意图：短了接不住、讲不透（含情感倾诉——老人在难过/孤独时
# 更需要被好好回应，压短反而显得敷衍）
_LONG_INTENTS = {"story_request", "memory_recall", "emotional_sharing"}


def reply_max_tokens(message: str, context: Dict[str, Any]) -> int:
    """按本轮内容动态决定回复长度上限（两条生成路径共用）。

    原则：
    - 功能意图（寒暄/提醒/放歌/玩游戏）走短档；讲故事、接往事、回忆追问走
      长档；其余日常对话走中档。
    - 风险等级 high 一律短档——危机干预时啰嗦是伤害，必须清晰短促。
    - 强烈负面情绪（强度 ≥0.8）压回短档：人正在激动时听不进长篇。
    - 老人这轮说了很多（>60 字）且落在中档时升一档——他说得多，
      通常期待被认真回应，回太短会显得敷衍。

    说明：长度只影响"总共生成多少"，不影响流式首字延迟（首 token 照常早出），
    所以长档的代价只是总时长变长，不会让老人多等第一个字。
    """
    intent = context.get("intent", "casual_chat")
    emotion = context.get("emotion", "neutral")
    intensity = float(context.get("emotion_intensity") or 0.0)

    # 危机：无论什么意图，一律短
    if context.get("risk_level") == "high":
        return REPLY_TOKENS_SHORT
    if intent in _SHORT_INTENTS:
        return REPLY_TOKENS_SHORT

    if intent in _LONG_INTENTS or emotion == "nostalgic":
        tokens = REPLY_TOKENS_LONG
    else:
        tokens = REPLY_TOKENS_MEDIUM

    # 情绪正在顶点 → 压回短档。
    # ⚠️ 只对"生气"这么做：火头上短促一句能降温，长篇容易对着怼。
    #    难过/孤独/焦虑时**不能**压短——那正是最需要被好好回应的时候，
    #    压短会显得敷衍（这个坑 2026-10-19 实测后发现并修正）。
    if emotion == "angry" and intensity >= 0.8:
        return REPLY_TOKENS_SHORT

    # 老人讲了不少（>30 字，约两三句）→ 升一档：他说得多，
    # 通常期待被认真回应，回太短会显得敷衍。（只从中档升，长档不再加）
    if tokens == REPLY_TOKENS_MEDIUM and len((message or "").strip()) > 30:
        tokens = REPLY_TOKENS_LONG

    return tokens

# 情境分析只带最近几条历史。实测把 13 条历史全塞进去，这一步会从 0.9s 涨到 2.2s；
# 而情境判断主要依赖"当前这句话 + 少量上下文"，多塞收益低、代价高。
ANALYSIS_HISTORY_TURNS = 4


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
    """情境分析工具：识别老人当前情绪、意图、场景、需求与风险。

    只取最近 ANALYSIS_HISTORY_TURNS 条历史（见常量处的实测说明）。
    """
    history = _deps.memory.short.recent_messages(user_id)[-ANALYSIS_HISTORY_TURNS:]
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
        # M4：本轮预选的追问缺口（None = 不追问）。记账在 chat 路由做。
        "elicitation": ctx.elicitation,
        "_ctx": ctx,  # 内部对象，供 generate 工具直接复用
    }


def reply_length_rule(message: str, context: Dict[str, Any]) -> str:
    """与 reply_max_tokens 同档的长度话术，注入 system prompt。

    光放开 max_tokens 不够——模型天生倾向短回复，主 prompt 里又有
    "必须遵守 60 字以内"的强约束，不换掉这句话，长档实际也只产出三五十字。
    """
    tokens = reply_max_tokens(message, context)
    if tokens >= REPLY_TOKENS_LONG:
        return LENGTH_RULE_LONG
    if tokens <= REPLY_TOKENS_SHORT:
        return LENGTH_RULE_SHORT
    return LENGTH_RULE_DEFAULT


def build_reply_messages(
    user_id: str, message: str, context: Dict[str, Any]
) -> List[Dict[str, str]]:
    """构造生成阶段的 messages（画像 + 记忆 + 情境 + 策略 + 实时表情）。

    由 generate_reply（非流式）与 stream_reply（流式）共用，
    避免"流式/非流式"两条路径行为分叉。
    """
    ctx = context["_ctx"]
    messages = build_messages(ctx, message,
                              length_rule=reply_length_rule(message, context))
    # 摄像头表情识别结果（5 分钟内有效）作为额外情境注入，
    # 让回复语气贴合老人当下表情；没有识别记录时完全不影响原链路
    latest_face = face_emotion.latest(user_id)
    if latest_face:
        minutes = latest_face["age_seconds"] // 60
        when = "刚才" if minutes < 1 else f"{minutes} 分钟前"
        messages.append({
            "role": "system",
            "content": (
                f"[实时表情] 摄像头识别到老人{when}的表情是"
                f"「{latest_face['label_cn']}」（置信度 {latest_face['score']:.0f}%）。"
                "请在回复中自然照顾到这一情绪，不必点破摄像头。"
            ),
        })

    # 长档场景（讲故事/接往事/回忆追问）光放开 max_tokens 不够——模型天生倾向
    # 短回复，不提示的话长档实际也只产出三五十字，"该长时长"形同虚设。
    # 长度话术已由 reply_length_rule() 注入主 prompt（替换其中的固定长度段），
    # 这里不再重复追加，避免两条指令互相打架。
    return messages


def reply_temperature(context: Dict[str, Any]) -> float:
    """高风险时降低温度稳住语气，其余情况保持自然。两条生成路径共用。"""
    return 0.5 if context["_ctx"].risk_level == "high" else 0.8


@tool
async def generate_reply(user_id: str, message: str,
                         context: Dict[str, Any]) -> str:
    """回复生成工具：注入画像+记忆+情境+策略，调用 Qwen 生成。"""
    ctx = context["_ctx"]
    messages = build_reply_messages(user_id, message, context)
    # DEBUG: 打印画像和 system prompt 关键部分
    logger.info("[DEBUG] user_id=%s, profile_name=%s, prompt_block=%s",
                user_id, ctx.profile.name, ctx.profile.prompt_block())
    logger.info("[DEBUG] system_prompt (first 800 chars): %s",
                messages[0]["content"][:800])
    # max_tokens 按本轮内容动态分档（寒暄短、故事长），见 reply_max_tokens
    return await _deps.client.chat(messages, temperature=reply_temperature(context),
                                   max_tokens=reply_max_tokens(message, context))


async def prepare(user_id: str, message: str) -> Dict[str, Any]:
    """只跑 analyze + context 两段（不含生成），返回 {analysis, context}。

    供流式接口复用与 /chat 完全相同的前置逻辑：先拿到情境分析与检索结果，
    再决定怎么生成，避免两条路径的画像/记忆注入出现差异。
    """
    analysis = await analyze_situation.ainvoke({
        "user_id": user_id, "message": message,
    })
    ctx = await build_context.ainvoke({
        "user_id": user_id, "message": message, "analysis": analysis,
    })
    return {"analysis": analysis, "context": ctx}


async def stream_reply(user_id: str, message: str, context: Dict[str, Any]):
    """流式生成回复：逐段 yield 文本增量（供 SSE 接口使用）。

    相比 chat() 一次性返回，首字延迟从"整段生成完"降到"首个 token"，
    老人能立刻看到/听到开头，体感快得多。
    """
    messages = build_reply_messages(user_id, message, context)
    async for piece in _deps.client.chat_stream(
        messages, temperature=reply_temperature(context),
        max_tokens=reply_max_tokens(message, context),
    ):
        yield piece


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
