"""M1 建表迁移测试：确认两条建表路径都能建出回忆录四张表。

- 同步路径 `init_db()`（legacy _SCHEMA）：dev 同步链路与所有 pytest 用例走这条；
- 异步路径 ORM `Base.metadata.create_all`（生产与 dev 启动走这条）。

两条路径必须同时维护（开发计划 §4.2 的 P2）——只改一处会导致测试或 dev 看不到表。

⚠ 注意：**不要在本模块导入期写 os.environ["COMPANION_DB_PATH"]**。
`get_conn()` 是在调用时读环境变量的，若此处全局覆盖，会连带污染 test_chat.py
（它也在导入期设置该变量并 init_db），导致其用例连到一个空库。
因此这里改用 case 级 monkeypatch，用完自动还原。异步那条则直接对临时库
create_all，完全不碰全局 settings / engine，避免影响其他测试。
"""
import sqlite3

import pytest

from app.db import init_db

STORY_TABLES = {
    "life_stories",
    "story_elicitation_queue",
    "story_media",
    "story_compilations",
}


@pytest.fixture()
def db_path(monkeypatch, tmp_path) -> str:
    """每个用例一个全新 SQLite 文件，并只在用例内覆盖 COMPANION_DB_PATH。"""
    path = str(tmp_path / "story_test.db")
    monkeypatch.setenv("COMPANION_DB_PATH", path)
    init_db()
    return path


def _names(path: str, sql: str) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {row[0] for row in conn.execute(sql)}
    finally:
        conn.close()


def _columns(path: str, table: str) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def test_init_db_creates_story_tables(db_path):
    tables = _names(db_path, "SELECT name FROM sqlite_master WHERE type='table'")
    assert STORY_TABLES.issubset(tables)


def test_story_indexes_present(db_path):
    indexes = _names(db_path, "SELECT name FROM sqlite_master WHERE type='index'")
    assert {"ix_life_stories_user_status", "ix_life_stories_user_eras"} <= indexes
    assert "ix_story_queue_user_status" in indexes
    assert "ix_story_compilations_user" in indexes


def test_life_stories_has_contract_columns(db_path):
    """契约2/5 依赖的列必须真实存在，不能只靠应用层约定。"""
    assert {"visibility", "visibility_locked", "avoid_flag", "raw_dialogue"} <= _columns(
        db_path, "life_stories"
    )


def test_init_db_is_idempotent(db_path):
    """重复执行不应报错（CREATE TABLE IF NOT EXISTS）。"""
    init_db()
    init_db()
    tables = _names(db_path, "SELECT name FROM sqlite_master WHERE type='table'")
    assert STORY_TABLES.issubset(tables)


def test_orm_metadata_creates_story_tables(tmp_path):
    """异步路径：直接对临时库跑 ORM create_all（等价于 init_async_db 的核心动作）。"""
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine

    from app.db.base import Base
    from app.db import models  # noqa: F401  确保模型注册到 metadata

    db_file = tmp_path / "async.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file.as_posix()}")

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(_setup())

    conn = sqlite3.connect(str(db_file))
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert STORY_TABLES.issubset(tables)
