import logging
import random
import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import bad_request, not_found, unauthorized
from app.core.security import (
    access_expires_seconds,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.db.redis import get_redis
from app.integrations import email as email_service
from app.schemas.auth import LoginDto, RegisterDto, ResetPasswordByEmailDto, SendResetCodeDto
from app.services import accounts

logger = logging.getLogger(__name__)

ACTIVATION_TOKEN_PREFIX = "email:activation:token:"
ACTIVATION_USER_PREFIX = "email:activation:user:"
ACTIVATION_TTL = 24 * 3600
RESET_CODE_PREFIX = "password:reset:code:"
RESET_CODE_TTL = 10 * 60
RESET_CODE_COOLDOWN = 60


def _login_result(auth_user: accounts.AuthUser) -> dict:
    return {
        "accessToken": create_access_token(auth_user.user_id, auth_user.username),
        "refreshToken": create_refresh_token(auth_user.user_id, auth_user.username),
        "tokenType": "Bearer",
        "expiresIn": access_expires_seconds(),
        "userInfo": auth_user.to_dict(),
    }


async def login(db: AsyncSession, dto: LoginDto) -> dict:
    user = await accounts.validate_credentials(db, dto.username, dto.password)
    await accounts.touch_last_login(db, user.user_id)
    return _login_result(user)


async def register(db: AsyncSession, dto: RegisterDto) -> dict:
    user_id, need_verify = await accounts.register_user(
        db,
        dto.username,
        dto.password,
        dto.email,
        dto.real_name,
        settings.require_email_verification,
    )
    if need_verify and dto.email:
        token = await _create_activation_token(user_id)
        try:
            await email_service.send_activation_email(dto.email, dto.username, token)
        except Exception as exc:
            await _delete_activation_token(token)
            logger.warning("激活邮件发送失败：%s", exc)
            raise bad_request("激活邮件发送失败，请稍后再试") from exc
        return {
            "userId": user_id,
            "message": "注册成功，请查收邮件激活账户",
            "emailVerificationRequired": True,
        }
    return {"userId": user_id, "message": "注册成功，请登录"}


async def _create_activation_token(user_id: str) -> str:
    redis = get_redis()
    existing = await redis.get(f"{ACTIVATION_USER_PREFIX}{user_id}")
    if existing:
        await redis.delete(f"{ACTIVATION_TOKEN_PREFIX}{existing}")
    token = secrets.token_hex(32)
    await redis.set(f"{ACTIVATION_TOKEN_PREFIX}{token}", user_id, ex=ACTIVATION_TTL)
    await redis.set(f"{ACTIVATION_USER_PREFIX}{user_id}", token, ex=ACTIVATION_TTL)
    return token


async def _consume_activation_token(token: str) -> str | None:
    redis = get_redis()
    user_id = await redis.get(f"{ACTIVATION_TOKEN_PREFIX}{token}")
    if not user_id:
        return None
    await redis.delete(f"{ACTIVATION_TOKEN_PREFIX}{token}")
    await redis.delete(f"{ACTIVATION_USER_PREFIX}{user_id}")
    return user_id


async def _delete_activation_token(token: str) -> None:
    redis = get_redis()
    user_id = await redis.get(f"{ACTIVATION_TOKEN_PREFIX}{token}")
    await redis.delete(f"{ACTIVATION_TOKEN_PREFIX}{token}")
    if user_id:
        await redis.delete(f"{ACTIVATION_USER_PREFIX}{user_id}")


async def verify_email(db: AsyncSession, token: str) -> dict:
    user_id = await _consume_activation_token(token)
    if not user_id:
        raise bad_request("激活链接无效或已过期")
    message = await accounts.activate_email(db, user_id)
    return {"message": message}


async def send_reset_code(db: AsyncSession, dto: SendResetCodeDto) -> dict:
    user = await accounts.find_by_email(db, dto.email)
    if user is None:
        raise not_found("该邮箱未注册")

    redis = get_redis()
    key = f"{RESET_CODE_PREFIX}{dto.email.lower()}"
    ttl = await redis.ttl(key)
    if ttl and ttl > RESET_CODE_TTL - RESET_CODE_COOLDOWN:
        raise bad_request("验证码已发送，请稍后再试")

    code = f"{random.randint(100000, 999999)}"
    await redis.set(key, code, ex=RESET_CODE_TTL)
    try:
        await email_service.send_reset_code_email(dto.email, user.username, code)
    except Exception as exc:
        await redis.delete(key)
        logger.warning("重置邮件发送失败：%s", exc)
        raise bad_request("邮件发送失败，请稍后再试") from exc
    return {"message": "验证码已发送"}


async def reset_password_by_email(db: AsyncSession, dto: ResetPasswordByEmailDto) -> dict:
    redis = get_redis()
    key = f"{RESET_CODE_PREFIX}{dto.email.lower()}"
    stored = await redis.get(key)
    if stored is None or stored != dto.code:
        raise bad_request("验证码错误或已过期")
    await accounts.reset_password_by_email(db, dto.email, dto.new_password)
    await redis.delete(key)
    return {"message": "密码重置成功，请登录"}


async def refresh(db: AsyncSession, refresh_token: str) -> dict:
    try:
        payload = decode_token(refresh_token, "refresh")
    except Exception as exc:
        raise unauthorized("refresh token 无效或已过期") from exc
    user = await accounts.build_auth_user(db, str(payload.get("sub")))
    return _login_result(user)
