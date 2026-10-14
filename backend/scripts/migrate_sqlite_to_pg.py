"""数据迁移脚本：旧 SQLite（users/conversations/memories/emotion_records）
   → 新 SQLAlchemy 异步数据库（accounts/elderly_profiles/conversations/...）。

用法：
    python scripts/migrate_sqlite_to_pg.py [--source PATH] [--dry-run]

默认源 = 旧 SQLite 路径（storage/companion.db 或 COMPANION_DB_PATH）。
默认目标 = 当前 Settings.database_url。

流程：
1) 读取旧 users 表 → 在 accounts 建老人账号 + elderly_profiles 画像
2) conversations / memories / emotion_records 按 user_id 关联平移
3) dry-run 模式只打印不写库

注意：旧 users 没有密码字段，迁移时给每个老人一个随机初始密码 + 强制要求
登录后改密（生产部署用），或仅打印提示由管理员后续处理。
"""
import argparse
import asyncio
import json
import logging
import os
import secrets
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.base import get_session_factory, init_async_db  # noqa: E402
from app.db.legacy import DB_PATH  # noqa: E402
from app.db.models import (  # noqa: E402
    Account,
    Conversation,
    ElderlyProfile,
    EmotionRecord,
    Memory,
)

logger = logging.getLogger("migrate")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _read_sqlite(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _gen_user_id() -> str:
    return f"e_{secrets.token_urlsafe(8)}"


def _gen_invite_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(6))


async def migrate(source: str, dry_run: bool = False) -> None:
    src = _read_sqlite(source)
    # 确保目标 schema 已建好
    if not dry_run:
        await init_async_db()
    factory = get_session_factory()

    # ---------- 1. users → accounts + elderly_profiles ----------
    users = src.execute("SELECT user_id, profile, created_at FROM users").fetchall()
    logger.info("源库 users 共 %d 行", len(users))
    async with factory() as session:  # type: AsyncSession
        for u in users:
            old_user_id = u["user_id"]
            try:
                profile_data = json.loads(u["profile"] or "{}")
            except json.JSONDecodeError:
                profile_data = {}
            # 用旧 user_id 作为登录用户名（迁移时用户名冲突由调用方处理）
            username = old_user_id
            existing = await session.execute(
                # 简化：直接尝试 insert，冲突则跳过
                # 生产可用 select first；演示脚本简化处理
            )
            account = Account(
                user_id=old_user_id,  # 保留旧 user_id，业务数据无需改
                username=username,
                password_hash=hash_password(secrets.token_urlsafe(16)),  # 随机初始密码
                role="elderly",
                invite_code=_gen_invite_code(),
                is_active=True,
            )
            profile = ElderlyProfile(
                user_id=old_user_id,
                name=profile_data.get("name", "老人家"),
                age=profile_data.get("age", 70),
                gender=profile_data.get("gender", "未知"),
                dialect=profile_data.get("dialect", ""),
                interests=profile_data.get("interests", []),
                favorite_music=profile_data.get("favorite_music", []),
                favorite_stories=profile_data.get("favorite_stories", []),
                family=profile_data.get("family", []),
                life_experience=profile_data.get("life_experience", []),
                conversation_preferences=profile_data.get("conversation_preferences", {}),
                taboos=profile_data.get("taboos", []),
            )
            if dry_run:
                logger.info("[dry-run] would create account %s / profile name=%s",
                            old_user_id, profile.name)
            else:
                session.add(account)
                session.add(profile)
        if not dry_run:
            await session.commit()
            logger.info("accounts + elderly_profiles 迁移完成")

    # ---------- 2. conversations ----------
    convs = src.execute("SELECT * FROM conversations ORDER BY id").fetchall()
    logger.info("源库 conversations 共 %d 行", len(convs))
    async with factory() as session:
        for c in convs:
            conv = Conversation(
                user_id=c["user_id"],
                role=c["role"],
                content=c["content"],
                current_topic=c["current_topic"] or "",
                emotion=c["emotion"] or "neutral",
                scene=c["scene"] or "conversation",
                intent=c["intent"] or "",
            )
            if dry_run:
                continue
            session.add(conv)
        if not dry_run:
            await session.commit()
            logger.info("conversations 迁移完成")

    # ---------- 3. memories ----------
    mems = src.execute("SELECT * FROM memories ORDER BY id").fetchall()
    logger.info("源库 memories 共 %d 行", len(mems))
    async with factory() as session:
        for m in mems:
            try:
                embedding = json.loads(m["embedding"]) if m["embedding"] else None
            except (json.JSONDecodeError, TypeError):
                embedding = None
            mem = Memory(
                user_id=m["user_id"],
                memory_type=m["memory_type"],
                content=m["content"],
                importance=m["importance"] or 0.5,
                embedding=embedding,
            )
            if dry_run:
                continue
            session.add(mem)
        if not dry_run:
            await session.commit()
            logger.info("memories 迁移完成")

    # ---------- 4. emotion_records ----------
    emos = src.execute("SELECT * FROM emotion_records ORDER BY id").fetchall()
    logger.info("源库 emotion_records 共 %d 行", len(emos))
    async with factory() as session:
        for e in emos:
            rec = EmotionRecord(
                user_id=e["user_id"],
                conversation_id=e["conversation_id"],
                emotion=e["emotion"],
                intensity=e["intensity"] or 0.0,
            )
            if dry_run:
                continue
            session.add(rec)
        if not dry_run:
            await session.commit()
            logger.info("emotion_records 迁移完成")

    src.close()
    logger.info("迁移全部完成（dry_run=%s）", dry_run)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=os.environ.get("COMPANION_DB_PATH", DB_PATH))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(migrate(args.source, args.dry_run))


if __name__ == "__main__":
    main()
