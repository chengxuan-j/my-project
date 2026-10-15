"""Pydantic 请求/响应模型。"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------- Auth ----------

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64,
                          pattern=r"^[A-Za-z0-9_\-\u4e00-\u9fff]+$")
    password: str = Field(..., min_length=6, max_length=128)
    role: str = Field(default="elderly", pattern="^(elderly|family)$")
    name: str = "老人家"
    email: Optional[str] = Field(default=None, max_length=254)
    email_code: Optional[str] = Field(default=None, pattern=r"^\d{6}$")


class LoginRequest(BaseModel):
    username: str
    password: str


class EmailCodeRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    purpose: str = Field(default="login", pattern="^(login|register|bind)$")


class EmailLoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    code: str = Field(..., pattern=r"^\d{6}$")


class TokenResponse(BaseModel):
    user_id: str
    username: str
    role: str
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    elderly_id: Optional[str] = None   # 家属绑定的第一个老人（如果有）
    invite_code: Optional[str] = None  # 老人专属：注册时返回，便于展示给家属
    email: Optional[str] = None


class RefreshRequest(BaseModel):
    refresh_token: str


class CurrentUserResponse(BaseModel):
    user_id: str
    username: str
    role: str
    elderly_id: Optional[str] = None
    email: Optional[str] = None


# ---------- Chat ----------

class ChatRequest(BaseModel):
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
    action: str = ""
    action_reason: str = ""
    recommendation: Optional[Dict[str, Any]] = None
    recommendation_id: Optional[str] = None  # 用于提交反馈
    degraded: bool = False
    recalled_memories: List[str] = Field(default_factory=list)
    knowledge_sources: List[Dict[str, Any]] = Field(default_factory=list)


# ---------- Profile ----------

class ProfileUpdateRequest(BaseModel):
    name: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    interests: Optional[List[str]] = None
    favorite_music: Optional[List[str]] = None
    favorite_stories: Optional[List[str]] = None
    family: Optional[List[str]] = None
    life_experience: Optional[List[str]] = None
    conversation_preferences: Optional[Dict[str, Any]] = None
    taboos: Optional[List[str]] = None
    health: Optional[str] = None   # 前端表单字段，后端会塞进 conversation_preferences.health_note


class MemoryItem(BaseModel):
    id: int
    memory_type: str
    content: str
    importance: float
    created_at: str


# ---------- Speech ----------

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


# ---------- Vision ----------

class VisionDescribeResponse(BaseModel):
    description: str
    question: str


class VisionReactResponse(BaseModel):
    description: str
    question: str
    actions: list[str] = []
    speech: str = ""
    dog_reached: bool = False


# ---------- Family ----------

class BindElderlyRequest(BaseModel):
    elderly_username: str = Field(..., min_length=1)
    invite_code: str = Field(..., min_length=6, max_length=6)
    relationship_name: str = "家属"


# ---------- Alert ----------

class AlertResponse(BaseModel):
    id: int
    elderly_user_id: str
    alert_type: str
    severity: str
    title: str
    detail: str
    is_acknowledged: bool
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[str] = None
    created_at: str


class EmotionTrendDay(BaseModel):
    date: str
    dominant_emotion: str
    avg_intensity: float
    record_count: int


# ---------- Face Emotion（DeepFace 表情识别） ----------

class FaceEmotionResponse(BaseModel):
    face_found: bool
    emotion: str = ""                # deepface 原生标签（happy/sad/...）
    emotion_label: str = ""          # 中文标签
    score: float = 0.0               # 主表情置信度 0~100
    scores: dict[str, float] = {}    # 7 类表情得分
    region: Optional[dict] = None    # 人脸框 {x,y,w,h}
    dog_reacted: bool = False        # 是否触发了机器狗安慰
    dog_reached: bool = False        # 狗是否实际收到指令
    speech: str = ""                 # 安慰时说的话
    created_at: str = ""


# ---------- Feedback ----------

class RecommendationFeedbackRequest(BaseModel):
    recommendation_type: str = Field(..., pattern="^(music|story)$")
    recommendation_title: str = Field(..., min_length=1, max_length=128)
    feedback_type: str = Field(..., pattern="^(like|dislike|skip)$")
    conversation_id: Optional[int] = None
