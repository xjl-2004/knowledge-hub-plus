from pydantic import Field

from app.schemas.base import CamelModel


class UpdateProfileDto(CamelModel):
    email: str | None = None
    real_name: str | None = None
    avatar: str | None = None


class ChangePasswordDto(CamelModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=6)


class ResetPasswordDto(CamelModel):
    new_password: str = Field(min_length=6)


class CreateUserDto(CamelModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=6)
    email: str | None = None
    real_name: str | None = None
    avatar: str | None = None
    status: int | None = None
    role_codes: list[str] | None = None


class UpdateUserDto(CamelModel):
    email: str | None = None
    real_name: str | None = None
    avatar: str | None = None
    status: int | None = None


class AssignRolesDto(CamelModel):
    role_codes: list[str]
