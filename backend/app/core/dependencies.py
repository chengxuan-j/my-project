"""FastAPI 依赖注入：JWT 解析 + 用户加载。

用法：
    @router.get("/me")
    async def me(current: Account = Depends(get_current_user)):
        return current
"""
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TOKEN_TYPE_ACCESS, try_decode
from app.db.base import get_db
from app.db.models import Account
from app.repositories.account_repo import AccountRepo

# auto_error=False：未带 token 时返回 None，由依赖函数决定抛 401
_bearer = HTTPBearer(auto_error=False)


async def get_current_account(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    session: AsyncSession = Depends(get_db),
) -> Account:
    """解析 Authorization: Bearer <token> → 加载 Account。失败抛 401。"""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 Authorization 头",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = try_decode(credentials.credentials, expected_type=TOKEN_TYPE_ACCESS)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token 无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id: str = payload.get("sub", "")
    account = await AccountRepo(session).get_by_user_id(user_id)
    if account is None or not account.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="账号不存在或已停用",
        )
    return account


async def require_elderly(
    account: Account = Depends(get_current_account),
) -> Account:
    if account.role != "elderly":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="仅老人账号可用"
        )
    return account


async def require_family(
    account: Account = Depends(get_current_account),
) -> Account:
    if account.role != "family":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="仅家属账号可用"
        )
    return account
