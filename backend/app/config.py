"""应用配置（Pydantic Settings 多环境版）。

全部从环境变量 / .env 读取。默认值面向开发环境（SQLite），生产通过环境变量覆盖。
兼容旧字段名（QWEN_API_KEY/DASHSCOPE_API_KEY/QWEN_TIMEOUT），保证现有 .env 仍然可用。
"""
import os
from functools import lru_cache
from typing import List, Optional

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录 = backend/（app/ 的上一级）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE_DIR, ".env")

# 加载 .env（不覆盖已有系统环境变量），保证 os.getenv 也能取到
load_dotenv(ENV_PATH)

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class Settings(BaseSettings):
    """运行期配置。所有值可用 .env 或环境变量覆盖。"""

    model_config = SettingsConfigDict(
        env_file=ENV_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # ---------- Qwen / LLM ----------
    qwen_api_key: str = ""
    qwen_base_url: str = DEFAULT_BASE_URL
    qwen_model: str = "kimi-k3"
    # 情境分析（情绪/意图/话题/场景）是结构化分类任务，必须用**非推理**的轻量模型。
    # 推理模型（如 kimi-k3）会把 token 全耗在思维链上、content 返回空，导致分析降级
    # 且单步耗时 10s+（2026-10-16 实测 kimi-k3 11.19s vs qwen-flash 2.01s，同句对比）。
    qwen_analysis_model: str = "qwen-flash"
    # 图像理解兜底：小智视觉服务没起、或本地表情模型缺依赖时用它
    # 注意 qwen-vl-plus 已下线（model_not_found），当前可用的是 qwen3-vl-plus
    qwen_vision_model: str = "qwen3-vl-plus"
    # 寒暄/短闲聊用快模型：实测首字 qwen-flash 0.32s vs qwen-plus 1.03s；
    # 情绪倾诉/故事/健康等仍走 qwen-plus，不为速度牺牲共情质量。
    qwen_fast_model: str = "qwen-flash"
    embedding_model: str = "text-embedding-v3"
    # 推理模型（qwen3 系列如 qwen3.7-flash）默认会先吐一大段思维链，
    # content 要等思考完才出来：2026-10-28 实测同一句话「想女儿了」
    # 开思考 9.76s / 关思考 2.97s。陪伴场景等 10 秒不可接受，所以允许显式关掉。
    # None = 不传该参数（保持服务端默认，兼容非推理模型）；
    # False = 关思考；True = 强制开。
    qwen_enable_thinking: Optional[bool] = None
    # 兼容旧环境变量名 QWEN_TIMEOUT
    request_timeout: float = Field(default=60.0, validation_alias="QWEN_TIMEOUT")

    # ---------- 语音（ASR / TTS） ----------
    # fun-asr 支持普通话 + 七大方言（官话/吴/湘/赣/客/闽/粤），
    # 是"老人说方言"能被听懂的关键；paraformer-v2 只适合普通话。
    asr_model: str = "fun-asr"
    asr_fallback_model: str = "paraformer-v2"
    tts_model: str = "qwen-audio-3.0-tts-flash"
    tts_voice: str = "longanhuan_v3.6"
    # 方言音色必须配 qwen3-tts 系列（Sunny=四川、Kiki=粤语…），
    # 老的 longanhuan 音色在它上面会报 InvalidVoice。
    tts_dialect_model: str = "qwen3-tts-flash"

    # ---------- 数据库 ----------
    # 开发默认 SQLite（aiosqlite），生产切 postgresql+asyncpg://...
    database_url: str = "sqlite+aiosqlite:///./storage/companion.db"

    # ---------- JWT ----------
    jwt_secret_key: str = "dev-secret-change-in-prod"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # ---------- 邮箱验证码 ----------
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    email_code_expire_minutes: int = 10
    email_code_cooldown_seconds: int = 60
    email_code_max_attempts: int = 5

    # ---------- 小智视觉服务（xiaozhi-esp32-server） ----------
    # 老人端拍照 → 转发给小智 MCP Vision 接口做图像理解
    xiaozhi_vision_url: str = "http://127.0.0.1:8003/mcp/vision/explain"
    xiaozhi_device_id: str = "elderly_companion_web"
    # 默认走小智的 web_test_client 测试通道（无需 token）；
    # 正式环境可在智控台绑定设备后填设备 token
    xiaozhi_auth_token: str = ""
    vision_timeout: float = 60.0

    # ---------- 机器狗（ESP-Hi 固件 /control HTTP 接口） ----------
    dog_base_url: str = "http://10.1.56.231"
    dog_timeout: float = 5.0

    # ---------- 表情关怀话术（老人端表情识别 → 机器狗发声） ----------
    # false：写死话术库轮换（默认，零延迟零成本、稳定可预期）；
    # true：改用 Qwen 即时生成（失败自动降级写死），适合想听"新鲜话"的场景。
    care_llm_enabled: bool = False

    # ---------- 每日陪伴日报推送（家属端） ----------
    # 每天把老人与陪伴助手的聊天汇总（统计 + AI 摘要）推进家属看板
    digest_enabled: bool = True
    digest_hour: int = 20        # 推送时刻（Asia/Shanghai）
    digest_minute: int = 30
    # 调度器总开关：生产环境默认开；开发环境默认关，
    # 本地想验证定时任务时在 .env 设 SCHEDULER_ENABLED=true
    scheduler_enabled: bool = False

    # ---------- 回忆录（生平故事 / 时代轴 / 故事板） ----------
    # 2026-10-15 起改为「实时回忆模式」并默认开启：
    # 老人消息命中回忆类关键词（以前/当年/知青/粮票……）即触发一次 LLM 提取，
    # 判定是平生故事就以 archived 直接记档，并 SSE 实时推送绑定家属。
    # 不攒完整度、不需要老人确认；创伤/回避内容仍锁 private 不推送（契约2）。
    # 想关掉：.env 设 MEMOIR_ENABLED=false，/chat 行为回到纯陪伴。
    memoir_enabled: bool = True
    # 每轮会话最多追问几个缺口（契约3 硬上限）
    memoir_max_asks_per_session: int = 1
    # 同一缺口追问后的冷却天数（避免唠叨）
    memoir_gap_cooldown_days: int = 3
    # 夜间缺口扫描时刻（把候选算好，避免对话中现算）
    memoir_gap_scan_hour: int = 1
    memoir_gap_scan_minute: int = 30
    # 短片编排的故事板总时长上限（秒）
    memoir_storyboard_seconds: int = 60
    # 回忆照片落盘目录（相对 BASE_DIR）。刻意不挂 StaticFiles：
    # 照片必须走鉴权接口读，否则 trauma 故事的 private 照片等于"知道 URL 就能看"。
    memoir_media_dir: str = "storage/memoir_media"
    # 单张照片大小上限（MB）——与 vision 的 5MB 对齐，前端不必两套提示
    memoir_media_max_mb: int = 5

    # ---------- 应用 ----------
    environment: str = "development"          # development / staging / production
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"

    # 兼容旧字段：DASHSCOPE_API_KEY 作为 fallback
    def model_post_init(self, __context) -> None:  # type: ignore[override]
        if not self.qwen_api_key:
            self.qwen_api_key = (os.getenv("DASHSCOPE_API_KEY") or "").strip()
        self.qwen_base_url = self.qwen_base_url.rstrip("/")
        if self.is_production:
            if self.jwt_secret_key == "dev-secret-change-in-prod":
                raise ValueError("生产环境必须设置 JWT_SECRET_KEY，不能使用默认密钥")
            if self.database_url.startswith("sqlite"):
                raise ValueError("生产环境必须使用 PostgreSQL DATABASE_URL")

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from_email)


@lru_cache()
def get_settings() -> Settings:
    return Settings()
