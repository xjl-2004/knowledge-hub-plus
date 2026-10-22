from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import settings
from app.core.errors import unauthorized


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt(10)).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def parse_expires(value: str, default_seconds: int) -> int:
    import re

    match = re.fullmatch(r"(\d+)([smhd])", value.strip())
    if not match:
        return default_seconds
    number = int(match.group(1))
    unit = match.group(2)
    return {
        "s": number,
        "m": number * 60,
        "h": number * 3600,
        "d": number * 86400,
    }[unit]


def access_expires_seconds() -> int:
    return parse_expires(settings.jwt_access_expires, 7200)


def create_token(user_id: str, username: str, token_type: str, expires: str) -> str:
    payload = {
        "sub": str(user_id),
        "username": username,
        "type": token_type,
        "exp": datetime.now(timezone.utc) + timedelta(seconds=parse_expires(expires, 7200)),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def create_access_token(user_id: str, username: str) -> str:
    return create_token(user_id, username, "access", settings.jwt_access_expires)


def create_refresh_token(user_id: str, username: str) -> str:
    return create_token(user_id, username, "refresh", settings.jwt_refresh_expires)


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise unauthorized("token 无效或已过期") from exc
    if payload.get("type") != expected_type:
        raise unauthorized(f"无效的 {expected_type} token")
    return payload
