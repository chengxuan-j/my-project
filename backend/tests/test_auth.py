"""JWT 认证 + 账号 repo 的单元测试。

不依赖外部 API，使用 SQLite 内存模式。
"""
import asyncio
import os

# 在所有 app 模块导入前设置测试 DB
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "test-secret"

from app.core.security import (  # noqa: E402
    TOKEN_TYPE_ACCESS,
    TOKEN_TYPE_REFRESH,
    create_access_token,
    create_refresh_token,
    hash_password,
    try_decode,
    verify_password,
)


# ---------- 密码 ----------

def test_hash_and_verify_password():
    h = hash_password("hello123")
    assert h != "hello123"
    assert verify_password("hello123", h)
    assert not verify_password("wrong", h)


# ---------- JWT ----------

def test_access_token_roundtrip():
    token = create_access_token("u_test_1", role="elderly")
    payload = try_decode(token, expected_type=TOKEN_TYPE_ACCESS)
    assert payload is not None
    assert payload["sub"] == "u_test_1"
    assert payload["role"] == "elderly"
    assert payload["type"] == TOKEN_TYPE_ACCESS


def test_refresh_token_roundtrip():
    token, expires_at = create_refresh_token("u_test_2", role="family")
    payload = try_decode(token, expected_type=TOKEN_TYPE_REFRESH)
    assert payload is not None
    assert payload["sub"] == "u_test_2"
    assert payload["type"] == TOKEN_TYPE_REFRESH
    # 7 天后过期
    delta = expires_at.timestamp() - payload["iat"]
    assert 6 * 86400 < delta <= 8 * 86400


def test_access_token_rejected_as_refresh():
    token = create_access_token("u_test_3")
    payload = try_decode(token, expected_type=TOKEN_TYPE_REFRESH)
    assert payload is None  # 类型不匹配 → None


def test_tampered_token_rejected():
    token = create_access_token("u_test_4")
    bad = token[:-2] + "xx"
    assert try_decode(bad, expected_type=TOKEN_TYPE_ACCESS) is None


# ---------- 数据库 repo ----------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_account_repo_crud():
    async def _go():
        from app.db.base import dispose_engine, get_session_factory, init_async_db
        await dispose_engine()  # 重置 engine，确保用测试 DATABASE_URL
        await init_async_db()
        factory = get_session_factory()
        async with factory() as session:
            from app.repositories.account_repo import AccountRepo
            repo = AccountRepo(session)
            # 注册老人
            acc = await repo.create_elderly(
                "test_elderly", "pwd123", name="王阿姨", email="elder@example.com"
            )
            await session.commit()
            assert acc.user_id.startswith("e_")
            assert acc.role == "elderly"
            assert acc.invite_code is not None and len(acc.invite_code) == 6
            # 校验密码
            assert repo.verify(acc, "pwd123")
            assert not repo.verify(acc, "wrong")
            # 按 username 查
            found = await repo.get_by_username("test_elderly")
            assert found is not None and found.user_id == acc.user_id
            found_by_email = await repo.get_by_email("ELDER@example.com")
            assert found_by_email is not None and found_by_email.user_id == acc.user_id
            # 注册家属
            fam = await repo.create_family("test_family", "pwd123")
            await session.commit()
            assert fam.role == "family"
            assert fam.invite_code is None
        await dispose_engine()
    asyncio.run(_go())


def test_email_code_lifecycle():
    async def _go():
        from app.db.base import dispose_engine, get_session_factory, init_async_db
        from app.repositories.account_repo import AccountRepo
        from app.services.email_auth import EmailCodeService

        await dispose_engine()
        await init_async_db()
        factory = get_session_factory()
        async with factory() as session:
            await AccountRepo(session).create_family(
                "mail_family", "pwd123", email="family@example.com"
            )
            await session.commit()

            service = EmailCodeService(session)
            sent = await service.send_code("family@example.com", "login")
            assert sent["sent"] is True
            assert sent.get("debug_code") and len(sent["debug_code"]) == 6
            await session.commit()

            assert not await service.verify_code("family@example.com", "000000", "login")
            assert await service.verify_code(
                "family@example.com", sent["debug_code"], "login"
            )
            assert not await service.verify_code(
                "family@example.com", sent["debug_code"], "login"
            )

            register = await service.send_code("new@example.com", "register")
            assert register.get("debug_code")
            assert await service.verify_code(
                "new@example.com", register["debug_code"], "register"
            )
            await session.commit()
        await dispose_engine()

    asyncio.run(_go())


def test_bind_email_then_login_with_code():
    async def _go():
        from httpx import ASGITransport, AsyncClient

        from app.db.base import dispose_engine, init_async_db
        from app.main import app

        await dispose_engine()
        await init_async_db()

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            registered = await client.post(
                "/api/v1/auth/register",
                json={
                    "username": "email_bind_user",
                    "password": "pwd123",
                    "role": "family",
                },
            )
            assert registered.status_code == 200
            access_token = registered.json()["access_token"]

            bind_code = await client.post(
                "/api/v1/auth/email/code",
                json={"email": "bind@example.com", "purpose": "bind"},
            )
            assert bind_code.status_code == 200
            debug_bind_code = bind_code.json()["debug_code"]

            bound = await client.post(
                "/api/v1/auth/email/bind",
                headers={"Authorization": f"Bearer {access_token}"},
                json={"email": "bind@example.com", "code": debug_bind_code},
            )
            assert bound.status_code == 200
            assert bound.json() == {"email": "bind@example.com", "bound": True}

            login_code = await client.post(
                "/api/v1/auth/email/code",
                json={"email": "bind@example.com", "purpose": "login"},
            )
            assert login_code.status_code == 200

            logged_in = await client.post(
                "/api/v1/auth/email/login",
                json={
                    "email": "bind@example.com",
                    "code": login_code.json()["debug_code"],
                },
            )
            assert logged_in.status_code == 200
            assert logged_in.json()["user_id"] == registered.json()["user_id"]
            assert logged_in.json()["email"] == "bind@example.com"

        await dispose_engine()

    asyncio.run(_go())
