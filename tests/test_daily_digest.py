"""每日陪伴日报推送测试。

不依赖外部 LLM：monkeypatch 掉 QwenClient，验证
- 统计聚合（轮数 / 情绪分布 / 话题 / 时段）
- 日报消息写入（category=digest、sender_role=elderly、JSON content）
- 同日去重
- 无绑定家属 / 当天无对话时不推送

注意：每个测试整体包在独立事件循环里跑（asyncio.run），避免 SQLAlchemy
async engine 跨 loop 复用连接报 "attached to a different loop"。
"""
import asyncio
import os

# 在所有 app 模块导入前设置测试 DB
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "test-secret"

import pytest  # noqa: E402

from app.db.models import FamilyMessage  # noqa: E402
from app.repositories.account_repo import AccountRepo  # noqa: E402
from app.repositories.profile_repo import ConversationRepo, FamilyRepo  # noqa: E402
from app.services.digest_service import (  # noqa: E402
    build_stats,
    parse_digest_content,
)


class _FakeQwenClient:
    """替身 LLM：不发起真实请求。"""

    is_configured = True
    analysis_model = "fake-turbo"
    model = "fake-main"

    async def chat(self, messages, **kwargs):
        assert messages and messages[0]["role"] == "user"
        return "老人今天心情不错，聊了天气和晚饭，还提起想孙女了。"


@pytest.fixture()
def _db(monkeypatch):
    """初始化内存 DB，返回 session 工厂；屏蔽真实 LLM。"""
    from app.db.base import dispose_engine, get_session_factory, init_async_db

    monkeypatch.setattr("app.llm.qwen_client.QwenClient", _FakeQwenClient)

    async def _setup():
        await dispose_engine()
        await init_async_db()

    asyncio.run(_setup())
    return get_session_factory()


async def _seed_elderly_with_family(factory):
    """造：老人 + 家属 + 绑定 + 当天对话。返回 (elderly_id, family_id)。"""
    async with factory() as session:
        acc_repo = AccountRepo(session)
        elderly = await acc_repo.create_elderly(
            "digest_elder", "pwd123", name="王阿姨", email="e@example.com"
        )
        family = await acc_repo.create_family(
            "digest_family", "pwd123", email="f@example.com"
        )
        await FamilyRepo(session).bind(family.user_id, elderly.user_id, "女儿")
        conv_repo = ConversationRepo(session)
        await conv_repo.append(elderly.user_id, "user", "今天天气真好", current_topic="天气")
        await conv_repo.append(elderly.user_id, "assistant", "是呀，适合出去走走～")
        await conv_repo.append(
            elderly.user_id, "user", "就是有点闷", emotion="lonely", current_topic="心情"
        )
        await conv_repo.append(
            elderly.user_id, "user", "想孙女了", emotion="miss", current_topic="家人"
        )
        await conv_repo.append(
            elderly.user_id, "user", "心里空落落的", emotion="lonely", current_topic="心情"
        )
        await session.commit()
        return elderly.user_id, family.user_id


async def _count_digest(factory, elderly_user_id: str) -> int:
    from sqlalchemy import func, select

    async with factory() as session:
        return int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(FamilyMessage)
                    .where(FamilyMessage.elderly_user_id == elderly_user_id)
                )
            ).scalar()
            or 0
        )


# ---------- 纯统计 ----------

def test_build_stats_aggregates():
    from datetime import datetime, timezone

    from app.db.models import Conversation

    now = datetime.now(timezone.utc)
    convs = [
        Conversation(role="user", content="a", emotion="happy", current_topic="天气", created_at=now),
        Conversation(role="assistant", content="b", created_at=now),
        Conversation(role="user", content="c", emotion="lonely", current_topic="心情", created_at=now),
        Conversation(role="user", content="d", emotion="lonely", current_topic="家人", created_at=now),
    ]
    stats = build_stats(convs)
    assert stats["rounds"] == 3                       # 只数老人发言
    assert stats["main_emotion"] == "lonely"
    assert stats["main_emotion_label"] == "孤独"
    assert {t["topic"] for t in stats["topics"]} == {"天气", "心情", "家人"}
    assert stats["emotion_dist"][0]["count"] == 2
    assert stats["time_range"]                              # 非空


def test_parse_digest_content():
    import json

    payload = {"date": "2026-10-13", "summary": "s", "stats": {"rounds": 3}}
    assert parse_digest_content(json.dumps(payload, ensure_ascii=False)) == payload
    assert parse_digest_content("普通留言文本") is None
    assert parse_digest_content("{坏json") is None


# ---------- 定时任务 ----------

def test_daily_digest_job_creates_messages(_db):
    factory = _db

    async def _go():
        from app.scheduler.jobs.daily_digest import daily_digest_job

        elderly_id, family_id = await _seed_elderly_with_family(factory)
        await daily_digest_job()

        from sqlalchemy import select

        async with factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(FamilyMessage).where(
                            FamilyMessage.elderly_user_id == elderly_id
                        )
                    )
                ).scalars().all()
            )

        assert len(rows) == 1
        msg = rows[0]
        assert msg.category == "digest"
        assert msg.sender_role == "elderly"
        assert msg.family_user_id == family_id

        digest = parse_digest_content(msg.content)
        assert digest is not None
        assert digest["stats"]["rounds"] == 4
        assert digest["stats"]["main_emotion"] == "lonely"
        assert digest["summary"]                      # 摘要非空（Fake LLM）

    asyncio.run(_go())


def test_daily_digest_job_is_idempotent(_db):
    factory = _db

    async def _go():
        from app.scheduler.jobs.daily_digest import daily_digest_job

        elderly_id, _ = await _seed_elderly_with_family(factory)
        await daily_digest_job()
        await daily_digest_job()  # 同日再跑一次
        assert await _count_digest(factory, elderly_id) == 1  # 去重

    asyncio.run(_go())


def test_daily_digest_skips_elderly_without_family(_db):
    factory = _db

    async def _go():
        async with factory() as session:
            acc = await AccountRepo(session).create_elderly(
                "lonely_elder", "pwd123", name="李叔叔", email="l@example.com"
            )
            await ConversationRepo(session).append(
                acc.user_id, "user", "有人吗", current_topic="闲聊"
            )
            await session.commit()
            elderly_id = acc.user_id

        from app.scheduler.jobs.daily_digest import daily_digest_job

        await daily_digest_job()
        assert await _count_digest(factory, elderly_id) == 0  # 未绑定家属，不推送

    asyncio.run(_go())


def test_daily_digest_skips_silent_day(_db):
    """老人 3 天前聊过、今天没聊：不应生成日报。"""
    factory = _db

    async def _go():
        from datetime import datetime, timedelta

        from app.db.models import Conversation

        async with factory() as session:
            acc = await AccountRepo(session).create_elderly(
                "silent_elder", "pwd123", name="赵阿姨", email="z@example.com"
            )
            family = await AccountRepo(session).create_family(
                "silent_family", "pwd123", email="zf@example.com"
            )
            await FamilyRepo(session).bind(family.user_id, acc.user_id, "儿子")
            # 手动插一条 3 天前的对话（本地时间口径，与 job 查询一致；
            # server_default 只会写现在）
            session.add(
                Conversation(
                    user_id=acc.user_id,
                    role="user",
                    content="三天前聊过",
                    created_at=datetime.now() - timedelta(days=3),
                )
            )
            await session.commit()
            elderly_id = acc.user_id

        from app.scheduler.jobs.daily_digest import daily_digest_job

        await daily_digest_job()
        assert await _count_digest(factory, elderly_id) == 0

    asyncio.run(_go())
