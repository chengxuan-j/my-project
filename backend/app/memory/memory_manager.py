"""MemoryManager：编排画像 + 短期记忆 + 长期记忆。

对外能力：
- build_context(user_id, message) -> ChatContext（给 Prompt 拼装和路由响应用）
- save_turn(...)（本轮对话落库）
- save_extracted_memories(...)（Qwen 判断出的长期记忆写入，路由以后台任务调用）
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.companion.companion_policy import CompanionPolicy, PolicyDecision
from app.companion.safety import assess_safety
from app.config import get_settings
from app.content import music, stories
from app.emotion.emotion_analyzer import AnalysisResult
from app.memory.long_memory import LongMemoryStore
from app.memory.short_memory import ShortMemory, extract_topic
from app.memoir import elicitation
from app.profile.elderly_profile import ElderlyProfile, ProfileStore
from app.rag.knowledge_base import KnowledgeBase
from app.scene import scene_detector

logger = logging.getLogger(__name__)


@dataclass
class ChatContext:
    profile: ElderlyProfile
    history: List[Tuple[str, str]]                 # 短期记忆（最近 N 轮）
    current_topic: str = ""
    emotion: str = "neutral"
    emotion_intensity: float = 0.0
    scene: str = "conversation"
    intent: str = "casual_chat"
    need: str = "none"
    risk_level: str = "low"
    safety_directive: str = ""                   # 第 4 轮安全策略给生成阶段的指令
    analysis: Optional[AnalysisResult] = None      # 本轮 Qwen 情境分析结果
    decision: Optional[PolicyDecision] = None      # 第 5 轮陪伴策略决策
    recommendation: Optional[Dict[str, Any]] = None  # 第 6 轮推荐内容（音乐/故事）
    long_memories: List[Dict[str, Any]] = field(default_factory=list)
    knowledge_results: List[Dict[str, Any]] = field(default_factory=list)
    # M4：本轮的追问决定（含 follow_up_hint）。None = 本轮不追问。
    # 只是"预选"，真正记账由 chat 路由在**生成成功之后**做，见 elicitation。
    elicitation: Optional[Dict[str, Any]] = None
    # 健康关怀：当前未确认的吃药/复诊提醒。由 agent 层查好塞进来，
    # 只进 prompt 供 AI 自然提一句，不改变回答长度与策略。
    health_due: List[Dict[str, Any]] = field(default_factory=list)


class MemoryManager:
    def __init__(self, knowledge: Optional[KnowledgeBase] = None) -> None:
        self.profiles = ProfileStore()
        self.short = ShortMemory()
        self.long = LongMemoryStore()
        self.knowledge = knowledge or KnowledgeBase()

    async def build_context(self, user_id: str, message: str,
                            analysis: Optional[AnalysisResult] = None) -> ChatContext:
        """组装上下文。analysis 由路由先调用 EmotionAnalyzer 得到（第 4 轮）。"""
        profile = self.profiles.get(user_id)
        history = self.short.recent_messages(user_id)
        state = self.short.current_state(user_id)

        safety_directive = ""
        if analysis is not None:
            emotion = analysis.emotion
            intent = analysis.intent
            need = analysis.need
            intensity = analysis.emotion_intensity
            topic = analysis.topic or extract_topic(message) or state["current_topic"]
            scene, _late = scene_detector.resolve_scene(
                analysis.scene, message, fallback_used=analysis.degraded
            )
            # 安全评估：Qwen 判定 + 关键词兜底，得到最终 risk 与生成指令
            risk, safety_directive = assess_safety(message, analysis.risk_level, intent)
        else:
            emotion, intent, need, risk, intensity = (
                state["emotion"], state["intent"], "none", "low", 0.0
            )
            topic = extract_topic(message) or state["current_topic"]
            scene = state["scene"]

        # 长期记忆检索 + RAG 知识库：两路互不依赖，**并发执行**。
        # 实测各自 1.3~1.6s，串行会白等约 1.4s；并发后取较慢的一路。
        # 注意：topic 来自 analysis，所以必须在 analysis 之后发起。
        # 知识库检索带上最近几轮老人原话——查询改写需要上文来消解
        # "这个怎么办"这类指代（见 app/rag/rewrite.py 的规则门控）。
        #
        # 寒暄不查知识库：一句"你好/在吗"去检索既没有可用的资料，
        # 又白花一次 embedding（冷启动时能到 2.6s）。省掉这一步，
        # 老人打招呼时首个字能早出来约 0.3~2.5s。
        need_knowledge = not (intent == "greeting" and len(message.strip()) <= 10)
        long_memories, knowledge_results = await asyncio.gather(
            self.long.search_multi(user_id, [message, topic]),
            self.knowledge.search(
                f"{message} {topic}".strip(), user_id=user_id, top_k=4,
                history=[c for r, c in history if r == "user"][-3:],
            ) if need_knowledge else asyncio.sleep(0, result=[]),
        )

        # 第 5 轮：陪伴策略决策（规则引擎，确定性）
        analysis_obj = analysis or AnalysisResult(
            emotion=emotion, emotion_intensity=intensity, intent=intent,
            topic=topic, scene=scene, need=need, risk_level=risk,
        )
        decision = CompanionPolicy().decide(analysis_obj)

        # 第 6 轮：若决策要求推荐内容，本地算出推荐项（供生成与响应复用）
        # 查询反馈统计用于推荐加权
        from app.db import get_conn
        liked_music = set()
        disliked_music = set()
        liked_stories = set()
        disliked_stories = set()
        try:
            with get_conn() as conn:
                # 音乐反馈
                rows = conn.execute(
                    "SELECT recommendation_title, feedback_type FROM recommendation_feedback "
                    "WHERE user_id = ? AND recommendation_type = 'music'",
                    (user_id,)
                ).fetchall()
                for row in rows:
                    if row["feedback_type"] == "like":
                        liked_music.add(row["recommendation_title"])
                    elif row["feedback_type"] == "dislike":
                        disliked_music.add(row["recommendation_title"])
                # 故事反馈
                rows = conn.execute(
                    "SELECT recommendation_title, feedback_type FROM recommendation_feedback "
                    "WHERE user_id = ? AND recommendation_type = 'story'",
                    (user_id,)
                ).fetchall()
                for row in rows:
                    if row["feedback_type"] == "like":
                        liked_stories.add(row["recommendation_title"])
                    elif row["feedback_type"] == "dislike":
                        disliked_stories.add(row["recommendation_title"])
        except Exception:
            pass  # 表可能不存在，忽略错误

        recommendation = None
        if decision.action in ("recommend_music", "recommend_content"):
            recommendation = music.pick_for_chat(
                profile, emotion, scene,
                liked_titles=liked_music,
                disliked_titles=disliked_music,
            ) or None
        elif decision.action == "recommend_story":
            recs = stories.recommend(
                profile, emotion, limit=1,
                liked_titles=liked_stories,
                disliked_titles=disliked_stories,
            )
            recommendation = recs[0] if recs else None

        elicitation = await self._resolve_elicitation(
            user_id, message=message, history=history, topic=topic,
            risk_level=risk, emotion_intensity=intensity,
        )

        return ChatContext(
            profile=profile,
            history=history,
            current_topic=topic,
            emotion=emotion,
            emotion_intensity=intensity,
            scene=scene,
            intent=intent,
            need=need,
            risk_level=risk,
            safety_directive=safety_directive,
            analysis=analysis,
            decision=decision,
            recommendation=recommendation,
            long_memories=long_memories,
            knowledge_results=knowledge_results,
            elicitation=elicitation,
        )

    async def _resolve_elicitation(
        self,
        user_id: str,
        *,
        message: str,
        history: List[Tuple[str, str]],
        topic: str,
        risk_level: str,
        emotion_intensity: float,
    ) -> Optional[Dict[str, Any]]:
        """M4：算本轮要不要顺带追问一个回忆缺口。

        两道开关：`memoir_enabled` 未开时整段跳过（暗发布，零影响）；
        `risk_level != "low"` 时干脆不算——elicitation 内部还会再拦一次，
        这里提前短路是为了不白查一次库。

        只做**预选**，不记账：生成失败就等于没问出口，不该占用会话额度。
        """
        settings = get_settings()
        if not settings.memoir_enabled or risk_level != "low":
            return None

        # 「回复变短」的基线：只看老人自己的发言，助手的长回复会污染均值
        user_lens = [len(c) for role, c in history if role == "user" and c]
        avg_len = sum(user_lens) / len(user_lens) if user_lens else 0.0

        decision = await elicitation.preview_for_turn(
            user_id,
            risk_level=risk_level,
            current_len=len(message or ""),
            recent_user_len_avg=avg_len,
            emotion_intensity=emotion_intensity,
            topic=topic,
            max_asks_per_session=settings.memoir_max_asks_per_session,
        )
        return decision.as_dict() if decision else None

    def save_turn(self, user_id: str, ctx: ChatContext,
                  user_msg: str, ai_reply: str) -> int:
        """落库一轮对话；assistant 行携带本轮状态，并记录情绪历史。

        Returns:
            conversation_id
        """
        self.short.append(user_id, "user", user_msg,
                          {"current_topic": ctx.current_topic})
        conv_id = self.short.append(user_id, "assistant", ai_reply, {
            "current_topic": ctx.current_topic,
            "emotion": ctx.emotion,
            "scene": ctx.scene,
            "intent": ctx.intent,
        })
        # 情绪历史（非 neutral 才记，减少噪音）
        if ctx.emotion and ctx.emotion != "neutral":
            try:
                self.short.record_emotion(user_id, conv_id, ctx.emotion,
                                          ctx.emotion_intensity)
            except Exception:
                logger.exception("情绪记录失败 user_id=%s", user_id)
        return conv_id

    def should_compress_conversation(self, user_id: str) -> bool:
        """检查是否需要压缩对话历史。"""
        return self.short.should_compress(user_id)

    async def save_extracted_memories(self, user_id: str,
                                     memories: List[Dict[str, Any]]) -> List[int]:
        """写入 Qwen 判断出的长期记忆（去重由 LongMemoryStore 负责），返回新增 id 列表。"""
        ids = []
        for m in memories:
            new_id = await self.long.add(user_id, m["memory_type"], m["memory"],
                                         m.get("importance", 0.5))
            if new_id is not None:
                ids.append(new_id)
        return ids
