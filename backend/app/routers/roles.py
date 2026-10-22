from fastapi import APIRouter, Depends

from app.core.deps import DbSession, require_permissions, require_roles
from app.schemas.rbac import AssignPermissionIdsDto, CreateRoleDto, UpdateRoleDto
from app.services import accounts

router = APIRouter(prefix="/roles", tags=["roles"])
admin_only = [Depends(require_roles(accounts.ROLE_ADMIN))]


@router.get("/list", dependencies=admin_only)
async def list_roles(db: DbSession):
    return await accounts.list_roles(db)


@router.post("", dependencies=admin_only)
async def create_role(db: DbSession, dto: CreateRoleDto):
    return await accounts.create_role(db, dto.role_name, dto.role_code, dto.description)


@router.get("/{role_id}", dependencies=admin_only)
async def get_role(db: DbSession, role_id: str):
    role = await accounts.get_role_or_throw(db, role_id)
    return accounts.role_vo(role, with_status=True)


@router.put("/{role_id}", dependencies=admin_only)
async def update_role(db: DbSession, role_id: str, dto: UpdateRoleDto):
    return await accounts.update_role(
        db, role_id, dto.role_name, dto.description, dto.status
    )


@router.delete("/{role_id}", dependencies=admin_only)
async def delete_role(db: DbSession, role_id: str):
    await accounts.delete_role(db, role_id)
    return {"message": "删除成功"}


@router.get(
    "/{role_id}/permissions",
    dependencies=[
        Depends(require_roles(accounts.ROLE_ADMIN)),
        Depends(require_permissions("system:role")),
    ],
)
async def get_role_permissions(db: DbSession, role_id: str):
    ids = await accounts.get_role_permission_ids(db, role_id)
    return {"roleId": role_id, "permissionIds": ids}


@router.put(
    "/{role_id}/permissions",
    dependencies=[
        Depends(require_roles(accounts.ROLE_ADMIN)),
        Depends(require_permissions("system:role")),
    ],
)
async def assign_role_permissions(
    db: DbSession, role_id: str, dto: AssignPermissionIdsDto
):
    ids = await accounts.assign_role_permissions(db, role_id, dto)
    return {"roleId": role_id, "permissionIds": ids}
