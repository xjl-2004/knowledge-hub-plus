from pydantic import Field

from app.schemas.base import CamelModel


class LoginDto(CamelModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class RegisterDto(CamelModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=6)
    email: str | None = None
    real_name: str | None = None


class RefreshTokenDto(CamelModel):
    refresh_token: str = Field(min_length=1)


class SendResetCodeDto(CamelModel):
    email: str = Field(min_length=1)


class ResetPasswordByEmailDto(CamelModel):
    email: str = Field(min_length=1)
    code: str = Field(min_length=1)
    new_password: str = Field(min_length=6)
