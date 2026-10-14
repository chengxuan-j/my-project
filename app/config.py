"""应用配置（Pydantic Settings 多环境版）。

全部从环境变量 / .env 读取。默认值面向开发环境（SQLite），生产通过环境变量覆盖。
兼容旧字段名（QWEN_API_KEY/DASHSCOPE_API_KEY/QWEN_TIMEOUT），保证现有 .env 仍然可用。
"""
import os
from functools import lru_cache
from typing import List

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录 = elderly_companion/
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
    qwen_analysis_model: str = "kimi-k3"
    embedding_model: str = "text-embedding-v3"
    # 兼容旧环境变量名 QWEN_TIMEOUT
    request_timeout: float = Field(default=60.0, validation_alias="QWEN_TIMEOUT")

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

    # ---------- 每日陪伴日报推送（家属端） ----------
    # 每天把老人与陪伴助手的聊天汇总（统计 + AI 摘要）推进家属看板
    digest_enabled: bool = True
    digest_hour: int = 20        # 推送时刻（Asia/Shanghai）
    digest_minute: int = 30
    # 调度器总开关：生产环境默认开；开发环境默认关，
    # 本地想验证定时任务时在 .env 设 SCHEDULER_ENABLED=true
    scheduler_enabled: bool = False

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
