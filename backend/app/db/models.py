"""SQLAlchemy ORM 模型。

设计说明：
- accounts：登录账号（老人 + 家属共用一张表，role 区分）
- elderly_profiles：老人画像（一对一挂在 accounts 上，role=elderly 才有）
- family_elderly_bindings：家属 ↔ 老人多对多绑定，invite_code 用于家属绑定流程
- refresh_tokens：刷新令牌（支持吊销）
- conversations / memories / emotion_records：业务数据，user_id 即老人 user_id

字段类型说明：
- JSON 字段：在 SQLite 与 PostgreSQL 下都用 SQLAlchemy JSON 类型，PG 下会自动用 JSONB
- embedding：先用 JSON 存 list[float]，生产切 PG 后再用 pgvector 替换（保留同名以便切换）
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


# ---------------------------------------------------------------------------
# 账号
# ---------------------------------------------------------------------------

class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(254), unique=True, index=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="elderly")  # elderly/family
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    invite_code: Mapped[Optional[str]] = mapped_column(
        String(32), unique=True, index=True, nullable=True,
        comment="老人的邀请码，家属用它绑定",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    elderly_profile: Mapped[Optional["ElderlyProfile"]] = relationship(
        back_populates="account", uselist=False, cascade="all, delete-orphan"
    )


class ElderlyProfile(Base):
    __tablename__ = "elderly_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("accounts.user_id", ondelete="CASCADE"),
        unique=True, index=True,
    )
    name: Mapped[str] = mapped_column(String(64), default="老人家")
    age: Mapped[int] = mapped_column(Integer, default=70)
    gender: Mapped[str] = mapped_column(String(8), default="未知")
    dialect: Mapped[str] = mapped_column(String(32), default="")
    interests: Mapped[List[str]] = mapped_column(JSON, default=list)
    favorite_music: Mapped[List[str]] = mapped_column(JSON, default=list)
    favorite_stories: Mapped[List[str]] = mapped_column(JSON, default=list)
    family: Mapped[List[str]] = mapped_column(JSON, default=list)
    life_experience: Mapped[List[str]] = mapped_column(JSON, default=list)
    conversation_preferences: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    taboos: Mapped[List[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    account: Mapped[Account] = relationship(back_populates="elderly_profile")


class FamilyElderlyBinding(Base):
    __tablename__ = "family_elderly_bindings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    family_user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("accounts.user_id", ondelete="CASCADE"), index=True
    )
    elderly_user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("accounts.user_id", ondelete="CASCADE"), index=True
    )
    relationship_name: Mapped[str] = mapped_column(String(32), default="家属")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("uq_family_elderly", "family_user_id", "elderly_user_id", unique=True),
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    token_hash: Mapped[str] = mapped_column(String(255))  # 不存明文
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class EmailVerificationCode(Base):
    """邮箱验证码。数据库只保存加盐哈希，不保存验证码明文。"""

    __tablename__ = "email_verification_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    purpose: Mapped[str] = mapped_column(String(16), default="login", index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    __table_args__ = (
        Index("idx_email_code_lookup", "email", "purpose", "id"),
    )


# ---------------------------------------------------------------------------
# 业务数据（挂在老人 user_id 下）
# ---------------------------------------------------------------------------

class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(16))          # user / assistant
    content: Mapped[str] = mapped_column(Text)
    current_topic: Mapped[str] = mapped_column(String(128), default="")
    emotion: Mapped[str] = mapped_column(String(32), default="neutral")
    scene: Mapped[str] = mapped_column(String(32), default="conversation")
    intent: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True,
    )

    __table_args__ = (Index("idx_conv_user_time", "user_id", "id"),)


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    memory_type: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    embedding: Mapped[Optional[List[float]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (Index("idx_mem_user_type", "user_id", "memory_type"),)


# ---------------------------------------------------------------------------
# RAG 知识库
# ---------------------------------------------------------------------------

class KnowledgeDocument(Base):
    """知识库原始文档。

    scope=global 表示在创建者的家庭范围共享；created_by 为空的系统资料才对所有老人可用。
    scope=elderly 只对指定老人可用。
    """

    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(500), default="")
    scope: Mapped[str] = mapped_column(String(16), default="global", index=True)
    elderly_user_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True,
        comment="scope=elderly 时限定可检索的老人 user_id",
    )
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_knowledge_scope_user", "scope", "elderly_user_id"),
    )


class KnowledgeChunk(Base):
    """文档分块及其 embedding；小规模部署无需额外向量数据库。"""

    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[Optional[List[float]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("uq_knowledge_doc_chunk", "document_id", "chunk_index", unique=True),
    )


class EmotionRecord(Base):
    __tablename__ = "emotion_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    conversation_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    emotion: Mapped[str] = mapped_column(String(32))
    intensity: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True,
    )


# ---------------------------------------------------------------------------
# 告警与反馈
# ---------------------------------------------------------------------------

class FamilyAlert(Base):
    """家属告警：情绪趋势异常、安全风险等。"""
    __tablename__ = "family_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    elderly_user_id: Mapped[str] = mapped_column(String(64), index=True)
    alert_type: Mapped[str] = mapped_column(String(32))   # negative_emotion_streak / safety / late_night
    severity: Mapped[str] = mapped_column(String(16), default="medium")  # low / medium / high
    title: Mapped[str] = mapped_column(String(128))
    detail: Mapped[str] = mapped_column(Text, default="")
    is_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True,
    )


class RecommendationFeedback(Base):
    """推荐反馈：记录用户对推荐内容的喜好。"""
    __tablename__ = "recommendation_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    conversation_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    recommendation_type: Mapped[str] = mapped_column(String(32))   # music / story
    recommendation_title: Mapped[str] = mapped_column(String(128))
    feedback_type: Mapped[str] = mapped_column(String(16))         # like / dislike / skip
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )


# ---------------------------------------------------------------------------
# 家人互动：留言 / 牵挂
# ---------------------------------------------------------------------------

class FamilyMessage(Base):
    """家属给老人的留言（暖心话/叮嘱），老人可读并可回应——双向互动载体。"""
    __tablename__ = "family_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    family_user_id: Mapped[str] = mapped_column(String(64), index=True)
    elderly_user_id: Mapped[str] = mapped_column(String(64), index=True)
    content: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(16), default="greeting")  # greeting/care/remind/miss
    # 发送方角色：family=家属发给老人；elderly=老人发给家属。接收方为另一方。
    sender_role: Mapped[str] = mapped_column(String(16), default="family")
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    reaction: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # 老人回应（emoji/短语）
    read_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True,
    )

    __table_args__ = (
        Index("idx_famsg_elderly_time", "elderly_user_id", "id"),
        Index("idx_famsg_family", "family_user_id"),
    )


# ---------------------------------------------------------------------------
# 回忆录：生平故事 / 缺口追问 / 附件 / 短片编排
#
# 六条契约在表结构上的体现：
# - 契约1 老人本人确认：status 的 archived 只能由老人端接口触发（见 api/v1/memoir.py）
# - 契约2 创伤强制 private：visibility_locked=True 时仓储层拒绝改 visibility
# - 契约5 不纠正记忆偏差：raw_dialogue 只追加，任何路径都不 UPDATE 该列
# - 契约6 不调视频 API：video_url 预留恒为 None，状态止于 prompt_ready
# ---------------------------------------------------------------------------

class LifeStory(Base):
    """一条生平故事（回忆录条目）。

    status 流转：draft（信息太少，不打扰老人）→ pending_confirm（够格给老人确认）
    → archived（老人确认留档）/ discarded（老人弃用，可恢复）。
    """

    __tablename__ = "life_stories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    elderly_user_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(128), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    # 原始对话片段，只增不改（契约5）。元素形如 {"role": "user", "content": "..."}
    raw_dialogue: Mapped[Optional[List[dict]]] = mapped_column(JSON, nullable=True)

    time_type: Mapped[str] = mapped_column(String(16), default="relative")
    time_value: Mapped[str] = mapped_column(String(64), default="")
    time_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    time_inferred: Mapped[bool] = mapped_column(Boolean, default=False)  # 由画像推算而来

    era_tags: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    place: Mapped[str] = mapped_column(String(64), default="")
    people: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    emotion_tone: Mapped[str] = mapped_column(String(16), default="平淡")
    completeness: Mapped[float] = mapped_column(Float, default=0.0)

    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    visibility: Mapped[str] = mapped_column(String(16), default="family")   # 契约2 默认 family
    visibility_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    avoid_flag: Mapped[bool] = mapped_column(Boolean, default=False)

    source_msg_ids: Mapped[Optional[List[int]]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_life_stories_user_status", "elderly_user_id", "status"),
        Index("ix_life_stories_user_eras", "elderly_user_id", "era_tags"),
    )


class StoryElicitationQueue(Base):
    """缺口追问队列：由提取结果里的 missing 推导，供 M4 挑时机自然带出。"""

    __tablename__ = "story_elicitation_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    elderly_user_id: Mapped[str] = mapped_column(String(64), index=True)
    story_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("life_stories.id", ondelete="CASCADE"), index=True
    )
    question: Mapped[str] = mapped_column(String(200), default="")
    gap_type: Mapped[str] = mapped_column(String(20), default="missing_detail")
    priority: Mapped[float] = mapped_column(Float, default=0.5)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/asked/answered/abandoned
    ask_count: Mapped[int] = mapped_column(Integer, default=0)
    cooldown_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    asked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    __table_args__ = (
        Index("ix_story_queue_user_status", "elderly_user_id", "status", "cooldown_until"),
    )


class StoryMedia(Base):
    """回忆录附件：家属或老人上传的照片/音频/视频（当前只做照片）。"""

    __tablename__ = "story_media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("life_stories.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(10), default="photo")  # photo/audio/video
    url: Mapped[str] = mapped_column(String(500), default="")
    caption: Mapped[str] = mapped_column(String(200), default="")
    uploaded_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class StoryCompilation(Base):
    """短片编排结果：只产出结构化提示词包 + 故事板，不生成任何画面（契约6）。

    status 当前只到 prompt_ready；rendering/done/failed 为将来接入视频 API 预留，
    video_url 同期限留且恒为 None。
    """

    __tablename__ = "story_compilations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    elderly_user_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(128), default="")
    story_ids: Mapped[Optional[List[int]]] = mapped_column(JSON, nullable=True)
    perspective: Mapped[str] = mapped_column(String(16), default="first_person")
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    prompt_package: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    prompt_model: Mapped[str] = mapped_column(String(64), default="")
    video_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # 预留，恒 None
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True,
    )

    __table_args__ = (
        Index("ix_story_compilations_user", "elderly_user_id", "created_at"),
    )
