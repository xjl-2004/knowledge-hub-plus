from fastapi import APIRouter, Depends, Query

from app.core.deps import CurrentUser, DbSession, require_roles
from app.schemas.rbac import AssignPermissionIdsDto
from app.schemas.users import (
    AssignRolesDto,
    ChangePasswordDto,
    CreateUserDto,
    ResetPasswordDto,
    UpdateProfileDto,
    UpdateUserDto,
)
from app.services import accounts

router = APIRouter(prefix="/users", tags=["users"])
admin_only = [Depends(require_roles(accounts.ROLE_ADMIN))]


@router.put("/me")
async def update_me(db: DbSession, user: CurrentUser, dto: UpdateProfileDto):
    return await accounts.update_profile(
        db, user.user_id, dto.email, dto.real_name, dto.avatar
    )


@router.get("/me/stats")
async def my_stats(db: DbSession, user: CurrentUser):
    return await accounts.get_user_statistics(db, user.user_id)


@router.put("/password/change")
async def change_password(db: DbSession, user: CurrentUser, dto: ChangePasswordDto):
    await accounts.change_password(db, user.user_id, dto.old_password, dto.new_password)
    return {"message": "密码修改成功"}


@router.get("/page", dependencies=admin_only)
async def page_users(
    db: DbSession,
    keyword: str | None = Query(None),
    status: int | None = Query(None),
    role_code: str | None = Query(None, alias="roleCode"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, alias="pageSize"),
):
    return await accounts.page_users(db, keyword, status, role_code, page, page_size)


@router.post("", dependencies=admin_only)
async def create_user(db: DbSession, dto: CreateUserDto):
    return await accounts.create_user(db, dto)


@router.get("/{user_id}", dependencies=admin_only)
async def get_user(db: DbSession, user_id: str):
    return await accounts.get_user_vo(db, user_id)


@router.put("/{user_id}", dependencies=admin_only)
async def update_user(db: DbSession, user_id: str, dto: UpdateUserDto):
    return await accounts.update_user(db, user_id, dto)


@router.delete("/{user_id}", dependencies=admin_only)
async def delete_user(db: DbSession, user_id: str):
    await accounts.delete_user(db, user_id)
    return {"message": "删除成功"}


@router.put("/{user_id}/password/reset", dependencies=admin_only)
async def reset_password(db: DbSession, user_id: str, dto: ResetPasswordDto):
    await accounts.reset_password(db, user_id, dto.new_password)
    return {"message": "密码重置成功"}


@router.get("/{user_id}/roles", dependencies=admin_only)
async def get_user_roles(db: DbSession, user_id: str):
    return {
        "userId": user_id,
        "roleCodes": await accounts.get_user_role_codes(db, user_id),
    }


@router.put("/{user_id}/roles", dependencies=admin_only)
async def assign_roles(db: DbSession, user_id: str, dto: AssignRolesDto):
    codes = await accounts.replace_roles(db, user_id, dto.role_codes)
    return {"userId": user_id, "roleCodes": codes}


@router.get("/{user_id}/permissions", dependencies=admin_only)
async def get_user_permissions(db: DbSession, user_id: str):
    await accounts.find_user_or_throw(db, user_id)
    return {
        "userId": user_id,
        "permissionCodes": await accounts.get_permission_codes(db, user_id),
        "directPermissionIds": await accounts.get_user_direct_permission_ids(db, user_id),
    }


@router.put("/{user_id}/permissions", dependencies=admin_only)
async def assign_user_permissions(
    db: DbSession, user_id: str, dto: AssignPermissionIdsDto
):
    ids = await accounts.assign_user_permissions(db, user_id, dto)
    return {"userId": user_id, "permissionIds": ids}
