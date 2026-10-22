from fastapi import APIRouter, Body, Depends, Query

from app.core.deps import CurrentUser, DbSession, require_permissions, require_roles
from app.schemas.teams import CreateTeamDto, UpdateTeamDto
from app.services import accounts

router = APIRouter(prefix="/teams", tags=["teams"])
admin_team = [
    Depends(require_roles(accounts.ROLE_ADMIN)),
    Depends(require_permissions("system:team")),
]


@router.post("", dependencies=admin_team)
async def create_team(db: DbSession, dto: CreateTeamDto):
    return await accounts.create_team(db, dto)


@router.get("/page", dependencies=admin_team)
async def page_teams(
    db: DbSession,
    keyword: str | None = Query(None),
    status: int | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, alias="pageSize"),
):
    return await accounts.page_teams(db, keyword, status, page, page_size)


@router.get("/mine")
async def list_mine(db: DbSession, user: CurrentUser):
    return await accounts.list_mine(db, user.user_id)


@router.get("/tree", dependencies=admin_team)
async def team_tree(db: DbSession, root_only: str | None = Query(None, alias="rootOnly")):
    return await accounts.team_tree(db, root_only == "true")


@router.get("/{team_id}", dependencies=admin_team)
async def get_team(db: DbSession, team_id: str):
    return await accounts.get_team_detail(db, team_id)


@router.post("/{team_id}/members", dependencies=admin_team)
async def add_members(db: DbSession, team_id: str, user_ids: list[str] = Body(...)):
    return await accounts.add_team_members(db, team_id, user_ids)


@router.delete("/{team_id}/members", dependencies=admin_team)
async def remove_members(db: DbSession, team_id: str, user_ids: list[str] = Body(...)):
    return await accounts.remove_team_members(db, team_id, user_ids)


@router.get("/{team_id}/members", dependencies=admin_team)
async def list_members(db: DbSession, team_id: str):
    return await accounts.list_team_members(db, team_id)


@router.put("/{team_id}", dependencies=admin_team)
async def update_team(db: DbSession, team_id: str, dto: UpdateTeamDto):
    return await accounts.update_team(db, team_id, dto)


@router.delete("/{team_id}", dependencies=admin_team)
async def delete_team(db: DbSession, team_id: str):
    await accounts.delete_team(db, team_id)
    return {"message": "删除成功"}
