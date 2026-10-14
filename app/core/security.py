"""JWT 签发/校验 + 密码哈希。

- Access Token：短时效（默认 30 分钟），放 Authorization Header
- Refresh Token：长时效（默认 7 天），存数据库支持吊销
- 密码：bcrypt（原生 API）+ SHA256 prehash（解决 bcrypt 72 字节限制）
"""
import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings

# Token 类型标识（写入 JWT payload 的 type 字段，防止互窜）
TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"


# ---------------------------------------------------------------------------
# 密码（bcrypt 原生 + SHA256 prehash）
# ---------------------------------------------------------------------------

def _prehash(secret: str) -> bytes:
    """SHA256 → base64 编码，固定长度 44 bytes，避免 bcrypt 72 字节限制。"""
    return base64.b64encode(hashlib.sha256(secret.encode("utf-8")).digest())


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_prehash(plain), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(plain), hashed.encode("utf-8"))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(
    sub: str,
    role: str = "elderly",
    expires_minutes: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    """签发 access token。sub=user_id，role=elderly/family。"""
    s = get_settings()
    exp_min = expires_minutes or s.access_token_expire_minutes
    now = _now()
    payload: Dict[str, Any] = {
        "sub": sub,
        "role": role,
        "type": TOKEN_TYPE_ACCESS,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=exp_min)).timestamp()),
        "jti": secrets.token_urlsafe(8),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, s.jwt_secret_key, algorithm=s.jwt_algorithm)


def create_refresh_token(
    sub: str,
    role: str = "elderly",
    expires_days: Optional[int] = None,
) -> tuple[str, datetime]:
    """签发 refresh token，返回 (token, expires_at)。token 本身只含 sub+jti+exp。"""
    s = get_settings()
    days = expires_days or s.refresh_token_expire_days
    now = _now()
    expires_at = now + timedelta(days=days)
    payload: Dict[str, Any] = {
        "sub": sub,
        "role": role,
        "type": TOKEN_TYPE_REFRESH,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": secrets.token_urlsafe(16),
    }
    token = jwt.encode(payload, s.jwt_secret_key, algorithm=s.jwt_algorithm)
    return token, expires_at


def decode_token(token: str, expected_type: Optional[str] = None) -> Dict[str, Any]:
    """解码并校验 token。expected_type 传入时强制校验 type 字段。

    抛出 JWTError 或 ValueError。
    """
    s = get_settings()
    payload = jwt.decode(token, s.jwt_secret_key, algorithms=[s.jwt_algorithm])
    if expected_type is not None and payload.get("type") != expected_type:
        raise ValueError(f"token 类型错误，期望 {expected_type}")
    return payload


def try_decode(token: str, expected_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """静默版 decode：失败返回 None，路由层用于 401 判定。"""
    try:
        return decode_token(token, expected_type=expected_type)
    except (JWTError, ValueError):
        return None
