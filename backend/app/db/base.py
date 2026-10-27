"""异步数据库引擎与会话工厂。

通过 DATABASE_URL 切换：
- 开发默认：sqlite+aiosqlite:///./storage/companion.db
- 生产：postgresql+asyncpg://user:pass@host:5432/companion

Base 在 app.db.models 中定义。本模块只负责引擎与会话。
"""
import logging
import os
import sqlite3
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import BASE_DIR, get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """所有 ORM 模型基类。"""


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _normalize_url(url: str) -> str:
    """相对路径的 SQLite URL 转成绝对路径，避免 cwd 不同导致连不上库。"""
    if url.startswith("sqlite") and "///./" in url:
        # sqlite+aiosqlite:///./storage/companion.db → 绝对路径
        rel = url.split("///./", 1)[1]
        abs_path = os.path.join(BASE_DIR, rel)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        return url.replace("///./" + rel, "///" + abs_path.replace("\\", "/"))
    return url


def get_engine() -> AsyncEngine:
    """全局唯一 AsyncEngine（懒加载）。"""
    global _engine
    if _engine is None:
        s = get_settings()
        url = _normalize_url(s.database_url)
        # SQLite 不需要 pool，PostgreSQL 用默认 pool 即可
        kwargs: dict = {"echo": False, "future": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"timeout": 30}
        _engine = create_async_engine(url, **kwargs)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：每个请求一个 AsyncSession。"""
    factory = get_session_factory()
    async with factory() as session:
        yield session


def _sqlite_path(url: str) -> str | None:
    """从 SQLAlchemy URL 取 SQLite 文件路径；非 SQLite 返回 None。"""
    if not url.startswith("sqlite") or "///" not in url:
        return None
    return url.split("///", 1)[1].split("?", 1)[0] or None


def _prepare_sqlite(url: str) -> None:
    """启动自愈：确认 SQLite 可写，并切回 WAL。

    背景（2026-10-26 事故）：进程被强杀后可能留下状态异常的 `-shm`，
    之后所有连接都会报 "attempt to write a readonly database"（登录直接 500）。
    这里在引擎创建前做一次写锁探测：写不进去且提示 readonly 时，
    删掉残留的 `-shm` 再试一次。单实例部署下安全；多实例部署请改用 PG。
    """
    path = _sqlite_path(url)
    if not path:
        return

    def _can_write() -> None:
        conn = sqlite3.connect(path, timeout=10)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.rollback()
        finally:
            conn.close()

    try:
        _can_write()
    except sqlite3.OperationalError as e:
        if "readonly" not in str(e).lower():
            logger.warning("SQLite 预检失败（非 readonly）: %s", e)
            return
        shm = path + "-shm"
        try:
            if os.path.exists(shm):
                os.remove(shm)
                logger.warning("检测到残留 -shm，已清理后重试: %s", shm)
            _can_write()
            logger.info("SQLite 写权限已恢复")
        except Exception as e2:  # noqa: BLE001
            logger.error("SQLite 仍不可写，登录等写操作会失败: %s", e2)
            return

    try:
        conn = sqlite3.connect(path, timeout=10)
        try:
            mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()
            logger.info("SQLite journal_mode=%s", mode[0] if mode else "?")
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001  切 WAL 失败不影响启动
        logger.warning("切换 WAL 失败: %s", e)


async def init_async_db() -> None:
    """启动时建表。生产环境用 Alembic 时本函数可省略。"""
    from app.db import models  # noqa: F401  确保模型已注册到 metadata

    _prepare_sqlite(_normalize_url(get_settings().database_url))

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # create_all 不会给已有 accounts 表补列；这里保持 SQLite/PostgreSQL 旧库兼容。
        if conn.dialect.name == "sqlite":
            columns = (await conn.exec_driver_sql("PRAGMA table_info(accounts)")).all()
            if "email" not in {row[1] for row in columns}:
                await conn.exec_driver_sql("ALTER TABLE accounts ADD COLUMN email VARCHAR(254)")
            await conn.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_accounts_email ON accounts (email)"
            )
        elif conn.dialect.name == "postgresql":
            await conn.exec_driver_sql(
                "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS email VARCHAR(254)"
            )
            await conn.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_accounts_email ON accounts (email)"
            )


async def dispose_engine() -> None:
    """测试/关闭时调用，释放连接池。"""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
