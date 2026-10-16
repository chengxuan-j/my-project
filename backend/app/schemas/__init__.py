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
    detector: str = ""               # 命中的检测器：opencv / retinaface（排查用）
    face_confidence: Optional[float] = None   # 人脸检测置信度 0~1
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


# ---------- 回忆录：生平故事 ----------

class StoryMediaItem(BaseModel):
    """回忆里的一张照片（M6）。

    `url` 是**鉴权**读接口路径（不是磁盘路径，也不是公开静态地址）——
    照片能不能看由服务端按"老人本人 / 已绑定家属 且 故事当前可见"判定，
    前端只负责带着 token 去取。

    `uploaded_by_role` 只暴露角色，不回传真实 user_id（家属之间也不必互认身份）。
    """

    id: int
    type: str = "photo"
    caption: str = ""
    url: str = ""
    # owner = 老人本人上传；family = 家属上传
    uploaded_by_role: str = "unknown"
    created_at: str = ""


class StoryItem(BaseModel):
    """老人端看到的回忆录条目。"""

    id: int
    title: str = ""
    summary: str = ""
    time_type: str = "relative"
    time_value: str = ""
    time_confidence: float = 0.0
    time_inferred: bool = False
    era_tags: List[str] = Field(default_factory=list)
    place: str = ""
    people: List[str] = Field(default_factory=list)
    emotion_tone: str = "平淡"
    completeness: float = 0.0
    status: str = "draft"
    created_at: str = ""
    # 留档时由 TTS 念出的确认语（复用 speech/tts）
    speak_text: str = ""
    # 挂在这条回忆上的照片（老人与家属都看得到）
    media: List[StoryMediaItem] = Field(default_factory=list)


class StoryActionRequest(BaseModel):
    """确认/弃用的动作来源：按钮还是语音（契约1 支持语音确认）。"""

    via: str = Field(default="button", pattern="^(button|voice)$")


class TimelineStory(StoryItem):
    """时间轴上的故事卡片。

    `display_time` 是**展示用**时间串（已含「约」字前缀），`time_value` 仍是
    原始值——契约5：推断只出现在展示层，原文永不改写。
    """

    display_time: str = ""
    # 推断依据的画像条目（给家属端解释「为什么猜这个时间」，可空）
    inferred_from: str = ""
    # 归属时代（多为 era_tags 命中项；推断出年份时由年份反推，也是推断）
    era: str = ""


class EraAxisGroup(BaseModel):
    """时代轴的一段（按 era_lexicon 规范名聚合）。"""

    era: str
    start_year: Optional[int] = None
    end_year: Optional[int] = None
    color: str = ""
    count: int = 0
    stories: List[TimelineStory] = Field(default_factory=list)


class TimelineStats(BaseModel):
    total: int = 0
    era_segments: int = 0
    in_era: int = 0
    in_absolute: int = 0
    unlocated: int = 0
    # 由画像保守推断出时间的条数（全部 time_inferred=True 且 confidence ≤ 0.5）
    inferred: int = 0


class AxisSpan(BaseModel):
    min_year: Optional[int] = None
    max_year: Optional[int] = None


class MemoirTimeline(BaseModel):
    """三组互斥且完备：每条故事恰好落一组。"""

    user_id: str = ""
    era_axis: List[EraAxisGroup] = Field(default_factory=list)
    absolute_axis: List[TimelineStory] = Field(default_factory=list)
    unlocated: List[TimelineStory] = Field(default_factory=list)
    axis_span: AxisSpan = Field(default_factory=AxisSpan)
    stats: TimelineStats = Field(default_factory=TimelineStats)


# ---------- 回忆录：故事板 / 提示词编排（M5） ----------

class CompilationCreateRequest(BaseModel):
    """创建一次短片编排。

    story_ids 为空表示"用我全部已留档的故事"。`total_seconds` 会被服务端
    夹到合理区间——老人端不该能传个 3600 进来。
    """

    title: str = Field(default="", max_length=64)
    story_ids: List[int] = Field(default_factory=list)
    perspective: str = Field(default="first_person", pattern="^(first_person|third_person)$")
    total_seconds: int = Field(default=60, ge=15, le=180)


class StoryboardScene(BaseModel):
    """故事板的一段镜头。契约6：只有提示词，没有画面。"""

    index: int
    story_id: int
    era: str = ""
    title: str = ""
    display_time: str = ""
    place: str = ""
    emotion_tone: str = ""
    duration_seconds: int = 0
    narration: str = ""
    # original = 直接用老人原话（契约4）；model = 模型改写
    narration_source: str = "model"
    visual_prompt: str = ""
    # 出处：一律是老人原话，由服务端写入，不采信模型
    source_evidence: str = ""


class CompilationItem(BaseModel):
    id: int
    title: str = ""
    perspective: str = "first_person"
    status: str = "queued"
    story_ids: List[int] = Field(default_factory=list)
    prompt_package: Optional[dict] = None
    created_at: str = ""
    # 契约6 的显式声明：本系统不产出视频，video_url 恒为 None
    video_url: Optional[str] = None
    # 真渲染=False（当前恒为 False）；前端据此只放提示词，不放"下载视频"
    rendered: bool = False
