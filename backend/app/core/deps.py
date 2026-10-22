from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import forbidden, unauthorized
from app.core.security import decode_token
from app.db.session import get_db

bearer = HTTPBearer(auto_error=False)
DbSession = Annotated[AsyncSession, Depends(get_db)]


@dataclass
class AuthUser:
    user_id: str
    username: str
    real_name: str | None
    email: str | None
    avatar: str | None
    roles: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    team_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "userId": self.user_id,
            "username": self.username,
            "realName": self.real_name,
            "email": self.email,
            "avatar": self.avatar,
            "roles": self.roles,
            "permissions": self.permissions,
            "teamIds": self.team_ids,
        }


async def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> AuthUser:
    if credentials is None or not credentials.credentials:
        raise unauthorized()
    payload = decode_token(credentials.credentials, "access")
    from app.services.accounts import build_auth_user

    return await build_auth_user(db, str(payload.get("sub")))


CurrentUser = Annotated[AuthUser, Depends(get_current_user)]


def require_roles(*role_codes: str):
    async def checker(user: CurrentUser) -> AuthUser:
        if not set(user.roles) & set(role_codes):
            raise forbidden("无权限：需要角色 " + " / ".join(role_codes))
        return user

    return checker


def require_permissions(*permission_codes: str):
    async def checker(user: CurrentUser) -> AuthUser:
        if not set(user.permissions) & set(permission_codes):
            raise forbidden("无权限：" + " / ".join(permission_codes))
        return user

    return checker


def require_roles_and_permissions(
    role_codes: tuple[str, ...], permission_codes: tuple[str, ...]
):
    async def checker(user: CurrentUser) -> AuthUser:
        if not set(user.roles) & set(role_codes):
            raise forbidden("无权限：需要角色 " + " / ".join(role_codes))
        if not set(user.permissions) & set(permission_codes):
            raise forbidden("无权限：" + " / ".join(permission_codes))
        return user

    return checker
