from fastapi import APIRouter, Depends, Query

from app.core.deps import DbSession, require_permissions, require_roles
from app.schemas.rbac import CreatePermissionDto, UpdatePermissionDto
from app.services import accounts

router = APIRouter(prefix="/permissions", tags=["permissions"])
admin = Depends(require_roles(accounts.ROLE_ADMIN))
system_permission = Depends(require_permissions("system:permission"))


@router.get("/list", dependencies=[admin, system_permission])
async def list_permissions(db: DbSession):
    return await accounts.list_permissions(db)


@router.get("/tree", dependencies=[admin, system_permission])
async def permission_tree(db: DbSession):
    return await accounts.permission_tree(db)


@router.get("/page", dependencies=[admin, system_permission])
async def page_permissions(
    db: DbSession,
    keyword: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, alias="pageSize"),
):
    return await accounts.page_permissions(db, keyword, page, page_size)


@router.get("/{permission_id}/children", dependencies=[admin, system_permission])
async def get_children(db: DbSession, permission_id: str):
    return await accounts.get_children(db, permission_id)


@router.get("/{permission_id}", dependencies=[admin, system_permission])
async def get_permission(db: DbSession, permission_id: str):
    return await accounts.get_permission(db, permission_id)


@router.post(
    "",
    dependencies=[
        Depends(require_roles(accounts.ROLE_ADMIN)),
        Depends(require_permissions("system:permission:create")),
    ],
)
async def create_permission(db: DbSession, dto: CreatePermissionDto):
    return await accounts.create_permission(db, dto)


@router.put(
    "/{permission_id}",
    dependencies=[
        Depends(require_roles(accounts.ROLE_ADMIN)),
        Depends(require_permissions("system:permission:edit")),
    ],
)
async def update_permission(db: DbSession, permission_id: str, dto: UpdatePermissionDto):
    return await accounts.update_permission(db, permission_id, dto)


@router.delete(
    "/{permission_id}",
    dependencies=[
        Depends(require_roles(accounts.ROLE_ADMIN)),
        Depends(require_permissions("system:permission:delete")),
    ],
)
async def delete_permission(db: DbSession, permission_id: str):
    await accounts.delete_permission(db, permission_id)
    return {"message": "删除成功"}
