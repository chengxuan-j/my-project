"""异步数据库引擎与会话工厂。

通过 DATABASE_URL 切换：
- 开发默认：sqlite+aiosqlite:///./storage/companion.db
- 生产：postgresql+asyncpg://user:pass@host:5432/companion

Base 在 app.db.models 中定义。本模块只负责引擎与会话。
"""
import os
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import BASE_DIR, get_settings


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


async def init_async_db() -> None:
    """启动时建表。生产环境用 Alembic 时本函数可省略。"""
    from app.db import models  # noqa: F401  确保模型已注册到 metadata

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
