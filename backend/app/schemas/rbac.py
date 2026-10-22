from pydantic import Field

from app.schemas.base import CamelModel


class CreateRoleDto(CamelModel):
    role_name: str = Field(min_length=1)
    role_code: str = Field(min_length=1)
    description: str | None = None


class UpdateRoleDto(CamelModel):
    role_name: str | None = None
    description: str | None = None
    status: int | None = None


class CreatePermissionDto(CamelModel):
    parent_id: str | None = None
    permission_name: str = Field(min_length=1)
    permission_code: str = Field(min_length=1)
    permission_type: int
    menu_url: str | None = None
    api_url: str | None = None
    method: str | None = None
    icon: str | None = None
    sort: int | None = None
    status: int | None = None


class UpdatePermissionDto(CamelModel):
    parent_id: str | None = None
    permission_name: str | None = None
    permission_code: str | None = None
    permission_type: int | None = None
    menu_url: str | None = None
    api_url: str | None = None
    method: str | None = None
    icon: str | None = None
    sort: int | None = None
    status: int | None = None


class AssignPermissionIdsDto(CamelModel):
    permission_ids: list[str]
