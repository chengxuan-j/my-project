"""认证路由：注册 / 登录 / 刷新 / 当前用户。"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_account, require_elderly
from app.core.security import (
    TOKEN_TYPE_REFRESH,
    create_access_token,
    create_refresh_token,
    hash_password,
    try_decode,
)
from app.db.base import get_db
from app.db.models import Account, ElderlyProfile
from app.repositories.account_repo import AccountRepo, RefreshTokenRepo
from app.repositories.profile_repo import ProfileRepo
from app.schemas import (
    CurrentUserResponse,
    EmailCodeRequest,
    EmailLoginRequest,
    LoginRequest,
    NameUpdateRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UsernameUpdateRequest,
)
from app.services.email_auth import (
    EmailCodeService,
    EmailCooldownError,
    EmailDeliveryError,
    InvalidEmailError,
    normalize_email,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_response(
    account: Account,
    refresh_token: str,
    elderly_id: str | None = None,
    name: str | None = None,
) -> TokenResponse:
    return TokenResponse(
        user_id=account.user_id,
        username=account.username,
        role=account.role,
        access_token=create_access_token(account.user_id, account.role),
        refresh_token=refresh_token,
        elderly_id=elderly_id,
        invite_code=account.invite_code if account.role == "elderly" else None,
        email=account.email,
        name=name,
    )


async def _display_name(account: Account, session: AsyncSession) -> str | None:
    """老人显示名取自画像 name；家属没有画像，返回 None（前端回退到 username）。"""
    if account.role != "elderly":
        return None
    return (await session.execute(
        select(ElderlyProfile.name).where(ElderlyProfile.user_id == account.user_id)
    )).scalar_one_or_none()


async def _elderly_id_for(account: Account, session: AsyncSession) -> str | None:
    if account.role == "family":
        from app.repositories.profile_repo import FamilyRepo
        bound = await FamilyRepo(session).list_elderly(account.user_id)
        return bound[0] if bound else None
    return account.user_id


async def _issue_session(account: Account, session: AsyncSession) -> TokenResponse:
    refresh_token, expires_at = create_refresh_token(account.user_id, account.role)
    payload = try_decode(refresh_token, expected_type=TOKEN_TYPE_REFRESH) or {}
    await RefreshTokenRepo(session).save(
        account.user_id,
        jti=payload.get("jti", ""),
        token_hash=hash_password(refresh_token),
        expires_at=expires_at,
    )
    await session.commit()
    return _token_response(
        account, refresh_token, await _elderly_id_for(account, session),
        name=await _display_name(account, session),
    )


@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest, session: AsyncSession = Depends(get_db)):
    """注册。role=elderly 自动创建空画像 + 邀请码；role=family 仅创建账号。"""
    repo = AccountRepo(session)
    existing = await repo.get_by_username(req.username)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="用户名已存在"
        )
    email = None
    if req.email:
        try:
            email = normalize_email(req.email)
        except InvalidEmailError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if await repo.get_by_email(email) is not None:
            raise HTTPException(status_code=409, detail="邮箱已绑定其他账号")
        if not req.email_code:
            raise HTTPException(status_code=400, detail="请输入邮箱验证码")
        valid = await EmailCodeService(session).verify_code(
            email, req.email_code, purpose="register"
        )
        if not valid:
            await session.commit()
            raise HTTPException(status_code=401, detail="邮箱验证码错误或已过期")
    if req.role == "elderly":
        account = await repo.create_elderly(req.username, req.password, req.name, email)
        elderly_id = account.user_id
    else:
        account = await repo.create_family(req.username, req.password, email)
        elderly_id = None

    refresh_token, expires_at = create_refresh_token(account.user_id, account.role)
    payload = try_decode(refresh_token, expected_type=TOKEN_TYPE_REFRESH) or {}
    await RefreshTokenRepo(session).save(
        account.user_id,
        jti=payload.get("jti", ""),
        token_hash=hash_password(refresh_token),
        expires_at=expires_at,
    )
    await session.commit()
    return _token_response(
        account, refresh_token, elderly_id,
        name=req.name if req.role == "elderly" else None,
    )


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, session: AsyncSession = Depends(get_db)):
    repo = AccountRepo(session)
    account = await repo.get_by_username(req.username)
    if account is None or not repo.verify(account, req.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误"
        )
    if not account.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已停用")

    return await _issue_session(account, session)


@router.post("/email/code")
async def send_email_code(
    req: EmailCodeRequest, session: AsyncSession = Depends(get_db)
):
    """发送邮箱登录验证码。生产环境不泄露邮箱是否存在。"""
    try:
        result = await EmailCodeService(session).send_code(req.email, req.purpose)
        await session.commit()
        return result
    except InvalidEmailError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EmailCooldownError as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except EmailDeliveryError as exc:
        await session.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/email/login", response_model=TokenResponse)
async def email_login(
    req: EmailLoginRequest, session: AsyncSession = Depends(get_db)
):
    """使用邮箱和一次性验证码登录。"""
    try:
        email = normalize_email(req.email)
        valid = await EmailCodeService(session).verify_code(email, req.code, purpose="login")
    except InvalidEmailError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    account = await AccountRepo(session).get_by_email(email)
    if not valid or account is None:
        await session.commit()
        raise HTTPException(status_code=401, detail="验证码错误或已过期")
    if not account.is_active:
        raise HTTPException(status_code=403, detail="账号已停用")
    return await _issue_session(account, session)


@router.post("/email/bind")
async def bind_email(
    req: EmailLoginRequest,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
):
    """当前登录账号验证并绑定邮箱，供后续验证码登录使用。"""
    try:
        email = normalize_email(req.email)
    except InvalidEmailError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    existing = await AccountRepo(session).get_by_email(email)
    if existing is not None and existing.user_id != account.user_id:
        raise HTTPException(status_code=409, detail="邮箱已绑定其他账号")
    if existing is not None and existing.user_id == account.user_id:
        return {"email": email, "bound": True}
    valid = await EmailCodeService(session).verify_code(email, req.code, purpose="bind")
    if not valid:
        await session.commit()
        raise HTTPException(status_code=401, detail="邮箱验证码错误或已过期")
    account.email = email
    await session.commit()
    return {"email": email, "bound": True}


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest, session: AsyncSession = Depends(get_db)):
    payload = try_decode(req.refresh_token, expected_type=TOKEN_TYPE_REFRESH)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="refresh_token 无效"
        )
    jti = payload.get("jti", "")
    user_id = payload.get("sub", "")

    tok_repo = RefreshTokenRepo(session)
    stored = await tok_repo.get_by_jti(jti)
    if not tok_repo.is_valid(stored):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="refresh_token 已失效"
        )

    account = await AccountRepo(session).get_by_user_id(user_id)
    if account is None or not account.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="账号不存在或已停用"
        )

    # 旋转 refresh token：旧的吊销，发新的
    await tok_repo.revoke(jti)
    new_refresh, expires_at = create_refresh_token(account.user_id, account.role)
    new_payload = try_decode(new_refresh, expected_type=TOKEN_TYPE_REFRESH) or {}
    await tok_repo.save(
        account.user_id,
        jti=new_payload.get("jti", ""),
        token_hash=hash_password(new_refresh),
        expires_at=expires_at,
    )
    await session.commit()

    elderly_id: str | None = None
    if account.role == "family":
        from app.repositories.profile_repo import FamilyRepo
        bound = await FamilyRepo(session).list_elderly(account.user_id)
        elderly_id = bound[0] if bound else None
    else:
        elderly_id = account.user_id

    return _token_response(
        account, new_refresh, elderly_id,
        name=await _display_name(account, session),
    )


@router.get("/me", response_model=CurrentUserResponse)
async def me(
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
):
    elderly_id: str | None = None
    if account.role == "family":
        from app.repositories.profile_repo import FamilyRepo
        bound = await FamilyRepo(session).list_elderly(account.user_id)
        elderly_id = bound[0] if bound else None
    else:
        elderly_id = account.user_id
    return CurrentUserResponse(
        user_id=account.user_id,
        username=account.username,
        role=account.role,
        elderly_id=elderly_id,
        email=account.email,
        name=await _display_name(account, session),
    )


@router.put("/name")
async def update_display_name(
    req: NameUpdateRequest,
    account: Account = Depends(require_elderly),
    session: AsyncSession = Depends(get_db),
):
    """修改老人的显示称呼。

    只改 `elderly_profiles.name`——这个名字会同时用于：导航栏问候、
    家属端老人列表、AI 对话 prompt 里的称呼。不碰 username（登录名），
    避免改个称呼把登录方式也改了。
    """
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="名字不能为空")
    if len(name) > 20:
        raise HTTPException(status_code=400, detail="名字最多 20 个字")

    repo = ProfileRepo(session)
    profile = await repo.get(account.user_id)
    if profile is None:
        profile = await repo.upsert(account.user_id, {"name": name})
    else:
        profile.name = name
    await session.commit()
    return {"name": name}


@router.put("/username")
async def update_username(
    req: UsernameUpdateRequest,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
):
    """修改登录用户名。

    这是登录凭据的一部分，所以要求验证当前密码；成功后旧的登录名立即失效。
    user_id / 邀请码 / 已绑定关系都不变，家属端不需要重新绑定。
    """
    username = req.username.strip()
    if username == account.username:
        return {"username": username}

    repo = AccountRepo(session)
    if not repo.verify(account, req.password):
        raise HTTPException(status_code=401, detail="当前密码不正确")

    existing = await repo.get_by_username(username)
    if existing is not None and existing.user_id != account.user_id:
        raise HTTPException(status_code=409, detail="这个登录名已经有人用了")

    account.username = username
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="这个登录名已经有人用了")
    return {"username": username}


@router.get("/invite-code")
async def my_invite_code(account: Account = Depends(get_current_account)):
    """老人查看自己的邀请码，家属输入这个码来绑定。"""
    if account.role != "elderly":
        raise HTTPException(status_code=403, detail="仅老人账号有邀请码")
    return {"invite_code": account.invite_code}
