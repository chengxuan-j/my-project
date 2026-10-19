"""FastAPI 应用入口。

设计：
- 新 API（带 JWT）：挂载在 /api/v1/*
- 旧 API（无认证，向后兼容 demo / 测试基线）：挂载在根路径 /chat、/profile/... 等
- CORS 开放给前端开发服务器（默认 http://localhost:3000）
- 生产环境不再挂载 web/ 静态目录（前端由 Next.js 独立部署）；开发仍保留以便直接访问旧版 index.html
"""

# ---------- 重型 native 库预加载（2026-10-19）----------
# ⚠️ 必须在**所有 app.* 模块之前**导入 torch，不能挪到文件后面。
#
# deepface 的表情模型走 PyTorch 后端（deepface.models.demography.pytorch.Emotion）。
# 若 torch 在 app.api.* / app.db / app.services 等模块**之后**才首次导入，Windows 上
# 会在 torch/__init__.py:496 加载 DLL 阶段直接 "access violation"，整个后端进程退出。
# 实测：`import torch` 单独跑 5/5 成功；`import app.api.v1.router; import torch` 100% 崩；
# 反过来 `import torch; import app.api.v1.router` 100% 成功。属导入顺序敏感的 DLL 冲突。
# 现象特征：服务启动十几~二十几秒后无声消失，日志停在 "FaceEmotionService 模型就绪"。
try:
    import torch  # noqa: F401  isort:skip
except Exception as _torch_err:  # noqa: BLE001  预加载失败不阻断启动
    torch = None  # type: ignore[assignment]
    print(f"[warn] torch 预加载失败，表情识别将退回懒加载: {_torch_err}", flush=True)

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as legacy_router
from app.api.v1.router import api_router
from app.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db import init_async_db, init_db
from app.llm.qwen_client import QwenClient

configure_logging()
logger = get_logger(__name__)

if torch is not None:
    logger.info("torch_preloaded", version=torch.__version__)
else:
    logger.warning("torch_preload_failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 旧版兼容 API 仅在开发/测试启用；生产只使用新版异步数据库。
    if not get_settings().is_production:
        init_db()
    # 新 SQLAlchemy 异步建表（MVP 用 create_all，后续切 Alembic）
    try:
        await init_async_db()
        logger.info("async_db_initialized")
    except Exception as e:
        logger.warning("async_db_init_failed", error=str(e))

    client = QwenClient()
    if not client.is_configured:
        logger.warning("qwen_not_configured")
    else:
        logger.info("qwen_configured", model=client.model)

    # 3) 启动 APScheduler（非开发环境）
    from app.scheduler.scheduler_manager import start_scheduler, stop_scheduler
    await start_scheduler()

    # 4) 后台预热表情识别模型（2026-10-16）：
    #    deepface + haar + retinaface 首次加载合计约 30~40 秒，不预热的话
    #    老人端第一帧识别会长时间无响应。用一张无脸灰图触发：haar 无检出
    #    → retinaface 兜底加载 → 两级 + 表情模型全部进内存。失败不影响启动。
    asyncio.create_task(_warmup_face_emotion())

    # 5) 后台预热 LLM/Embedding 的 HTTP 连接（2026-10-16）：
    #    首次调用要建 TCP+TLS，实测一次 embed 冷启动 1.21s、热态仅 0.12s。
    #    不预热的话，重启后第一位老人的第一句会白等约 1 秒。
    asyncio.create_task(_warmup_llm())

    yield

    # 6) 停止调度器
    await stop_scheduler()


async def _warmup_llm() -> None:
    """预热 Qwen chat / embedding 连接，以及 Agent 前置链路。

    实测：重启后**第一条真实请求**首个 delta 要 9s（原始连接 1.2s 之外，
    还有画像加载、LangGraph 首次执行、DB 会话建立等一次性开销）。
    这里除了热连接，还跑一次完整的 prepare()（分析 + 检索，不写任何状态），
    把整条前置链路预热，让第一位老人的第一句话不再白等。
    """
    try:
        client = QwenClient()
        if not client.is_configured:
            return
        # 一次极小 chat + 一次 embedding，把两条连接的池子都热起来
        await client.chat(
            [{"role": "user", "content": "你好"}], temperature=0.0, max_tokens=1
        )
        await client.embed(["预热"])
        logger.info("llm_connections_warmed_up")
    except Exception as e:  # noqa: BLE001  预热失败不影响启动
        logger.warning("llm_warmup_failed", error=str(e))
        return

    try:
        # 应用层预热：用库里第一位老人跑一次 prepare（只读，不落任何数据）
        from sqlalchemy import select

        from app.agent import companion_agent
        from app.db.base import get_session_factory
        from app.db.models import Account

        async with get_session_factory()() as session:
            uid = (
                await session.execute(
                    select(Account.user_id).limit(1)
                )
            ).scalar_one_or_none()
        if uid:
            await companion_agent.prepare(uid, "你好")
            logger.info("agent_pipeline_warmed_up")
    except Exception as e:  # noqa: BLE001
        logger.warning("agent_warmup_failed", error=str(e))


async def _warmup_face_emotion() -> None:
    """后台预热表情识别（失败只记日志，绝不阻断启动）。"""
    try:
        import cv2
        import numpy as np

        from app.services.face_emotion import face_emotion

        blank = np.full((240, 320, 3), 160, dtype=np.uint8)
        ok, buf = cv2.imencode(".jpg", blank)
        if not ok:
            return
        await face_emotion.analyze(buf.tobytes())
        logger.info("face_emotion_warmed_up")
    except Exception as e:  # noqa: BLE001
        logger.warning("face_emotion_warmup_failed", error=str(e))


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="老人情感陪伴 AI",
        version="0.2.0",
        lifespan=lifespan,
    )

    # CORS：允许 Next.js 前端跨域。
    # 开发环境（非 production）放开全部来源，便于多设备 + SSE 直连调试；
    # 生产环境按 CORS_ORIGINS 严格限制。
    origins = s.cors_origins_list
    allow_all = (not s.is_production) or ("*" in origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if allow_all else origins,
        allow_credentials=not allow_all,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 新 API（带 JWT）
    app.include_router(api_router)
    # 旧 API（无认证，向后兼容 demo + 测试基线）；已弃用，新代码请使用 /api/v1/*
    if not s.is_production:
        app.include_router(legacy_router, deprecated=True)

    # 前端由 Next.js 独立部署（localhost:3000），不再挂载旧版静态页面
    return app


app = create_app()
