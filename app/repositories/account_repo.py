"""账号数据访问层（SQLAlchemy 2.0 async）。"""
import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.db.models import Account, ElderlyProfile, RefreshToken


def _gen_user_id(prefix: str = "u") -> str:
    return f"{prefix}_{secrets.token_urlsafe(8)}"


def _gen_invite_code() -> str:
    """6 位邀请码：家属绑定老人用。去掉易混淆字符。"""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(6))


class AccountRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_username(self, username: str) -> Optional[Account]:
        stmt = select(Account).where(Account.username == username)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_email(self, email: str) -> Optional[Account]:
        stmt = select(Account).where(Account.email == email.strip().lower())
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_user_id(self, user_id: str) -> Optional[Account]:
        stmt = select(Account).where(Account.user_id == user_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_invite_code(self, code: str) -> Optional[Account]:
        stmt = select(Account).where(Account.invite_code == code)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create_elderly(
        self, username: str, password: str, name: str = "老人家",
        email: Optional[str] = None,
    ) -> Account:
        """注册老人账号：自动创建空画像 + 邀请码。"""
        account = Account(
            user_id=_gen_user_id("e"),
            username=username,
            email=email.strip().lower() if email else None,
            password_hash=hash_password(password),
            role="elderly",
            invite_code=_gen_invite_code(),
        )
        self.session.add(account)
        # 同时建一份空画像，避免后续 get 时空指针
        profile = ElderlyProfile(user_id=account.user_id, name=name)
        self.session.add(profile)
        await self.session.flush()
        return account

    async def create_family(
        self, username: str, password: str, email: Optional[str] = None
    ) -> Account:
        account = Account(
            user_id=_gen_user_id("f"),
            username=username,
            email=email.strip().lower() if email else None,
            password_hash=hash_password(password),
            role="family",
            invite_code=None,
        )
        self.session.add(account)
        await self.session.flush()
        return account

    def verify(self, account: Account, password: str) -> bool:
        return verify_password(password, account.password_hash)


class RefreshTokenRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(
        self, user_id: str, jti: str, token_hash: str, expires_at: datetime
    ) -> RefreshToken:
        tok = RefreshToken(
            user_id=user_id, jti=jti, token_hash=token_hash, expires_at=expires_at
        )
        self.session.add(tok)
        await self.session.flush()
        return tok

    async def get_by_jti(self, jti: str) -> Optional[RefreshToken]:
        stmt = select(RefreshToken).where(RefreshToken.jti == jti)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def revoke(self, jti: str) -> None:
        tok = await self.get_by_jti(jti)
        if tok:
            tok.revoked = True
            await self.session.flush()

    def is_valid(self, tok: Optional[RefreshToken]) -> bool:
        if tok is None or tok.revoked:
            return False
        # 注意：DB 时间可能是 naive，统一按 UTC aware 比较
        now = datetime.now(timezone.utc)
        exp = tok.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return exp > now
