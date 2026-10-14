"""邮箱验证码生成、发送与校验。"""
import asyncio
import hashlib
import hmac
import logging
import re
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Account, EmailVerificationCode

logger = logging.getLogger(__name__)

EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")


class InvalidEmailError(ValueError):
    pass


class EmailCooldownError(RuntimeError):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = max(1, retry_after)
        super().__init__(f"请在 {self.retry_after} 秒后重试")


class EmailDeliveryError(RuntimeError):
    pass


def normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if len(normalized) > 254 or not EMAIL_PATTERN.fullmatch(normalized):
        raise InvalidEmailError("邮箱格式不正确")
    return normalized


def hash_email_code(email: str, code: str) -> str:
    secret = get_settings().jwt_secret_key.encode("utf-8")
    message = f"{normalize_email(email)}:{code}".encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class EmailCodeService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()

    async def send_code(self, email: str, purpose: str = "login") -> dict:
        email = normalize_email(email)
        if purpose not in {"login", "register", "bind"}:
            raise ValueError("不支持的验证码用途")
        account = (await self.session.execute(
            select(Account).where(Account.email == email)
        )).scalar_one_or_none()

        # 始终返回相同的成功文案，避免生产环境通过接口枚举注册邮箱。
        eligible = account is not None and account.is_active if purpose == "login" else account is None
        if not eligible:
            return {
                "sent": True,
                "message": "如果该邮箱可以使用，验证码将发送到邮箱",
                "retry_after": self.settings.email_code_cooldown_seconds,
            }

        latest = (await self.session.execute(
            select(EmailVerificationCode)
            .where(
                EmailVerificationCode.email == email,
                EmailVerificationCode.purpose == purpose,
            )
            .order_by(EmailVerificationCode.id.desc())
            .limit(1)
        )).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if latest is not None and latest.created_at is not None:
            elapsed = (now - _as_utc(latest.created_at)).total_seconds()
            cooldown = self.settings.email_code_cooldown_seconds
            if elapsed < cooldown:
                raise EmailCooldownError(int(cooldown - elapsed + 0.999))

        code = f"{secrets.randbelow(1_000_000):06d}"
        await self.session.execute(
            update(EmailVerificationCode)
            .where(
                EmailVerificationCode.email == email,
                EmailVerificationCode.purpose == purpose,
                EmailVerificationCode.consumed.is_(False),
            )
            .values(consumed=True)
        )
        record = EmailVerificationCode(
            email=email,
            purpose=purpose,
            code_hash=hash_email_code(email, code),
            expires_at=now + timedelta(minutes=self.settings.email_code_expire_minutes),
        )
        self.session.add(record)
        await self.session.flush()

        debug_code = None
        if self.settings.smtp_configured:
            await asyncio.to_thread(self._send_email, email, code, purpose)
        elif self.settings.is_production:
            raise EmailDeliveryError("邮件服务尚未配置")
        else:
            debug_code = code
            logger.info("development_email_code_generated", extra={"email": email})

        response = {
            "sent": True,
            "message": "验证码已发送，请检查邮箱",
            "retry_after": self.settings.email_code_cooldown_seconds,
            "expires_in": self.settings.email_code_expire_minutes * 60,
        }
        if debug_code:
            response["debug_code"] = debug_code
            response["message"] = "开发环境未配置 SMTP，已生成测试验证码"
        return response

    async def verify_code(self, email: str, code: str, purpose: str = "login") -> bool:
        email = normalize_email(email)
        record = (await self.session.execute(
            select(EmailVerificationCode)
            .where(
                EmailVerificationCode.email == email,
                EmailVerificationCode.purpose == purpose,
                EmailVerificationCode.consumed.is_(False),
            )
            .order_by(EmailVerificationCode.id.desc())
            .limit(1)
            .with_for_update()
        )).scalar_one_or_none()
        if record is None:
            return False

        now = datetime.now(timezone.utc)
        if _as_utc(record.expires_at) <= now:
            record.consumed = True
            await self.session.flush()
            return False
        if record.attempts >= self.settings.email_code_max_attempts:
            record.consumed = True
            await self.session.flush()
            return False

        record.attempts += 1
        valid = hmac.compare_digest(record.code_hash, hash_email_code(email, code))
        if valid or record.attempts >= self.settings.email_code_max_attempts:
            record.consumed = True
        await self.session.flush()
        return valid

    def _send_email(self, recipient: str, code: str, purpose: str) -> None:
        settings = self.settings
        message = EmailMessage()
        action = {"register": "注册", "bind": "绑定邮箱"}.get(purpose, "登录")
        message["Subject"] = f"老人情感陪伴 AI {action}验证码"
        message["From"] = formataddr(("老人情感陪伴 AI", settings.smtp_from_email))
        message["To"] = recipient
        message.set_content(
            f"您的{action}验证码是：{code}\n\n"
            f"验证码 {settings.email_code_expire_minutes} 分钟内有效。"
            "如果不是您本人操作，请忽略这封邮件。"
        )
        smtp_cls = smtplib.SMTP_SSL if settings.smtp_use_ssl else smtplib.SMTP
        try:
            with smtp_cls(settings.smtp_host, settings.smtp_port, timeout=15) as client:
                if not settings.smtp_use_ssl:
                    client.ehlo()
                    if settings.smtp_use_tls:
                        client.starttls()
                        client.ehlo()
                if settings.smtp_username:
                    client.login(settings.smtp_username, settings.smtp_password)
                client.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            logger.warning("email_delivery_failed", extra={"error": str(exc)})
            raise EmailDeliveryError("验证码邮件发送失败，请稍后重试") from exc
