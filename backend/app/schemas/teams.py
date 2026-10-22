from pydantic import Field

from app.schemas.base import CamelModel


class CreateTeamDto(CamelModel):
    team_name: str = Field(min_length=1)
    team_code: str | None = None
    description: str | None = None
    leader_id: str | None = None
    parent_id: str | None = None
    sort: int | None = None
    status: int | None = None


class UpdateTeamDto(CamelModel):
    team_name: str | None = None
    team_code: str | None = None
    description: str | None = None
    leader_id: str | None = None
    parent_id: str | None = None
    sort: int | None = None
    status: int | None = None


class RemoveMembersDto(CamelModel):
    user_ids: list[str]
