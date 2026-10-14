"""SQLite 数据访问底座。

- 数据库路径：storage/companion.db（可用环境变量 COMPANION_DB_PATH 覆盖，测试用）
- 每次操作新建连接（FastAPI 线程池下最稳妥），WAL 模式提升并发
- 第 2 轮启用 users / conversations；memories / emotion_records 先建表，第 3/4 轮写入
"""
import logging
import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from app.config import BASE_DIR

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(BASE_DIR, "storage", "companion.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     TEXT PRIMARY KEY,
    profile     TEXT NOT NULL,            -- JSON：画像全量字段
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    role        TEXT NOT NULL,            -- user / assistant
    content     TEXT NOT NULL,
    -- 短期记忆状态（第 4 轮情绪/意图/场景分析后回填，本轮默认 neutral）
    current_topic   TEXT DEFAULT '',
    emotion         TEXT DEFAULT 'neutral',
    scene           TEXT DEFAULT 'conversation',
    intent          TEXT DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_conv_user_time ON conversations (user_id, id);

CREATE TABLE IF NOT EXISTS memories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    memory_type TEXT NOT NULL,            -- family / life_experience / interest / preference ...
    content     TEXT NOT NULL,
    importance  REAL NOT NULL DEFAULT 0.5,
    embedding   TEXT,                     -- JSON 数组：语义向量（text-embedding-v3，1024 维）
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_mem_user_type ON memories (user_id, memory_type);

CREATE TABLE IF NOT EXISTS emotion_records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    conversation_id INTEGER,
    emotion     TEXT NOT NULL,
    intensity   REAL NOT NULL DEFAULT 0.0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS elderly_profiles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL UNIQUE,
    name            TEXT DEFAULT '老人家',
    age             INTEGER DEFAULT 70,
    gender          TEXT DEFAULT '未知',
    dialect         TEXT DEFAULT '',
    interests       TEXT DEFAULT '[]',
    favorite_music  TEXT DEFAULT '[]',
    favorite_stories TEXT DEFAULT '[]',
    family          TEXT DEFAULT '[]',
    life_experience TEXT DEFAULT '[]',
    conversation_preferences TEXT DEFAULT '{}',
    taboos          TEXT DEFAULT '[]',
    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS family_alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    elderly_user_id TEXT NOT NULL,
    alert_type      TEXT NOT NULL,
    severity        TEXT NOT NULL DEFAULT 'medium',
    title           TEXT NOT NULL,
    detail          TEXT DEFAULT '',
    is_acknowledged INTEGER NOT NULL DEFAULT 0,
    acknowledged_by TEXT,
    acknowledged_at TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_alert_elderly ON family_alerts (elderly_user_id);
CREATE INDEX IF NOT EXISTS idx_alert_created ON family_alerts (created_at);

CREATE TABLE IF NOT EXISTS recommendation_feedback (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id               TEXT NOT NULL,
    conversation_id       INTEGER,
    recommendation_type   TEXT NOT NULL,
    recommendation_title  TEXT NOT NULL,
    feedback_type         TEXT NOT NULL DEFAULT 'skip',
    created_at            TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_feedback_user ON recommendation_feedback (user_id);
"""


def _db_path() -> str:
    return os.environ.get("COMPANION_DB_PATH", DB_PATH)


def init_db() -> None:
    path = _db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with get_conn() as conn:
        conn.executescript(_SCHEMA)
        _migrate(conn)
    logger.info("SQLite 初始化完成: %s", path)


def _migrate(conn: sqlite3.Connection) -> None:
    """已有数据库补列（embedding 是第 8 轮新增，老库需 ALTER）。"""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(memories)")}
    if "embedding" not in cols:
        conn.execute("ALTER TABLE memories ADD COLUMN embedding TEXT")
        logger.info("migration: memories 表新增 embedding 列")


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        yield conn
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise
    finally:
        conn.close()
