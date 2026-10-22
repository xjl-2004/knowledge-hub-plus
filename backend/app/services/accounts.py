from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AuthUser
from app.core.errors import bad_request, conflict, forbidden, not_found, unauthorized
from app.core.security import hash_password, verify_password
from app.core.snowflake import next_id
from app.models import (
    Document,
    Permission,
    Role,
    RolePermission,
    Team,
    TeamMember,
    User,
    UserPermission,
    UserRole,
)
from app.schemas.base import iso, page_result
from app.schemas.rbac import (
    AssignPermissionIdsDto,
    CreatePermissionDto,
    UpdatePermissionDto,
)
from app.schemas.teams import CreateTeamDto, UpdateTeamDto
from app.schemas.users import CreateUserDto, UpdateUserDto

ROLE_ADMIN = "ROLE_ADMIN"
ROLE_REVIEWER = "ROLE_REVIEWER"
ROLE_USER = "ROLE_USER"

ADMIN_OPERATION_PERMISSIONS = [
    "document:list",
    "document:create",
    "document:edit",
    "document:delete",
    "document:review",
    "document:category",
    "document:category:query",
    "document:tag",
    "document:version",
    "search",
    "system:user",
    "system:role",
    "system:permission",
    "system:permission:create",
    "system:permission:edit",
    "system:permission:delete",
    "system:team",
    "system:statistics",
    "system:settings",
]


def _id(value: Any) -> str:
    return str(value)


# ---------------------------------------------------------------- 角色与权限查询


async def get_role_codes(db: AsyncSession, user_id: str) -> list[str]:
    rows = await db.execute(
        select(Role.role_code)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == int(user_id), Role.status == 1)
    )
    return [row[0] for row in rows.all()]


async def get_permission_codes(db: AsyncSession, user_id: str) -> list[str]:
    uid = int(user_id)
    direct = await db.execute(
        select(Permission.permission_code)
        .join(UserPermission, UserPermission.permission_id == Permission.id)
        .where(
            UserPermission.user_id == uid,
            Permission.status == 1,
            Permission.deleted.is_(False),
        )
    )
    via_role = await db.execute(
        select(Permission.permission_code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .where(
            UserRole.user_id == uid,
            Permission.status == 1,
            Permission.deleted.is_(False),
        )
        .distinct()
    )
    codes = {row[0] for row in direct.all()} | {row[0] for row in via_role.all()}
    roles = await get_role_codes(db, user_id)
    if ROLE_ADMIN in roles:
        codes.update(ADMIN_OPERATION_PERMISSIONS)
    return list(codes)


async def get_user_ids_by_role_code(db: AsyncSession, role_code: str) -> list[str]:
    rows = await db.execute(
        select(User.id)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(
            Role.role_code == role_code,
            User.deleted.is_(False),
            User.status == 1,
        )
    )
    return [str(row[0]) for row in rows.all()]


async def list_accessible_team_ids(db: AsyncSession, user_id: str) -> list[str]:
    uid = int(user_id)
    member_rows = await db.execute(
        select(TeamMember.team_id).where(TeamMember.user_id == uid)
    )
    led_rows = await db.execute(
        select(Team.id).where(Team.leader_id == uid, Team.deleted.is_(False))
    )
    ids = {str(row[0]) for row in member_rows.all()} | {
        str(row[0]) for row in led_rows.all()
    }
    if not ids:
        return []
    rows = await db.execute(
        select(Team.id).where(Team.id.in_([int(i) for i in ids]), Team.deleted.is_(False))
    )
    return [str(row[0]) for row in rows.all()]


async def build_auth_user(db: AsyncSession, user_id: str) -> AuthUser:
    user = await find_user(db, user_id)
    if user is None:
        raise unauthorized("用户不存在")
    if user.status != 1:
        raise unauthorized("账户已禁用")
    return AuthUser(
        user_id=str(user.id),
        username=user.username,
        real_name=user.real_name,
        email=user.email,
        avatar=user.avatar,
        roles=await get_role_codes(db, user_id),
        permissions=await get_permission_codes(db, user_id),
        team_ids=await list_accessible_team_ids(db, user_id),
    )


# ---------------------------------------------------------------- 用户


def user_vo(user: User, role_codes: list[str]) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "username": user.username,
        "email": user.email,
        "realName": user.real_name,
        "avatar": user.avatar,
        "status": user.status,
        "lastLoginAt": iso(user.last_login_at),
        "createdAt": iso(user.created_at),
        "updatedAt": iso(user.updated_at),
        "roleCodes": role_codes,
    }


async def find_user(db: AsyncSession, user_id: str) -> User | None:
    result = await db.execute(
        select(User).where(User.id == int(user_id), User.deleted.is_(False))
    )
    return result.scalar_one_or_none()


async def find_user_or_throw(db: AsyncSession, user_id: str) -> User:
    user = await find_user(db, user_id)
    if user is None:
        raise not_found("用户不存在")
    return user


async def find_by_username(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(
        select(User).where(User.username == username, User.deleted.is_(False))
    )
    return result.scalar_one_or_none()


async def find_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(
        select(User).where(User.email == email, User.deleted.is_(False))
    )
    return result.scalar_one_or_none()


async def get_user_vo(db: AsyncSession, user_id: str) -> dict[str, Any]:
    user = await find_user_or_throw(db, user_id)
    return user_vo(user, await get_role_codes(db, user_id))


async def validate_credentials(db: AsyncSession, username: str, password: str) -> AuthUser:
    user = await find_by_username(db, username)
    if user is None:
        raise unauthorized("用户名或密码错误")
    if user.status != 1:
        raise unauthorized("账户已禁用")
    if user.email_verified == 0:
        raise unauthorized("账户未激活，请先验证邮箱")
    if not verify_password(password, user.password):
        raise unauthorized("用户名或密码错误")
    return await build_auth_user(db, str(user.id))


async def touch_last_login(db: AsyncSession, user_id: str) -> None:
    user = await find_user_or_throw(db, user_id)
    user.last_login_at = datetime.now()
    await db.commit()


async def register_user(
    db: AsyncSession,
    username: str,
    password: str,
    email: str | None,
    real_name: str | None,
    require_verification: bool,
) -> tuple[str, bool]:
    if await find_by_username(db, username):
        raise conflict("用户名已存在")
    if email and await find_by_email(db, email):
        raise conflict("邮箱已被使用")

    need_verify = require_verification and bool(email)
    user = User(
        id=next_id(),
        username=username,
        password=hash_password(password),
        email=email,
        real_name=real_name,
        status=0 if need_verify else 1,
        email_verified=0 if need_verify else 1,
    )
    db.add(user)
    await db.commit()
    await assign_role(db, str(user.id), ROLE_USER)
    return str(user.id), need_verify


async def create_user(db: AsyncSession, dto: CreateUserDto) -> dict[str, Any]:
    if await find_by_username(db, dto.username):
        raise conflict("用户名已存在")
    user = User(
        id=next_id(),
        username=dto.username,
        password=hash_password(dto.password),
        email=dto.email,
        real_name=dto.real_name,
        avatar=dto.avatar,
        status=dto.status if dto.status is not None else 1,
        email_verified=1,
    )
    db.add(user)
    await db.commit()
    role_codes = dto.role_codes if dto.role_codes else [ROLE_USER]
    await replace_roles(db, str(user.id), role_codes)
    return await get_user_vo(db, str(user.id))


async def update_user(db: AsyncSession, user_id: str, dto: UpdateUserDto) -> dict[str, Any]:
    user = await find_user_or_throw(db, user_id)
    if dto.email is not None:
        user.email = dto.email
    if dto.real_name is not None:
        user.real_name = dto.real_name
    if dto.avatar is not None:
        user.avatar = dto.avatar
    if dto.status is not None:
        user.status = dto.status
    user.updated_at = datetime.now()
    await db.commit()
    return await get_user_vo(db, user_id)


async def delete_user(db: AsyncSession, user_id: str) -> None:
    user = await find_user_or_throw(db, user_id)
    user.deleted = True
    await db.commit()


async def page_users(
    db: AsyncSession,
    keyword: str | None,
    status: int | None,
    role_code: str | None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    stmt = select(User).where(User.deleted.is_(False))
    if keyword and keyword.strip():
        kw = f"%{keyword.strip()}%"
        stmt = stmt.where(
            or_(
                User.username.ilike(kw),
                User.real_name.ilike(kw),
                User.email.ilike(kw),
            )
        )
    if status is not None:
        stmt = stmt.where(User.status == status)
    if role_code:
        stmt = (
            stmt.join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(Role.role_code == role_code)
        )

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = await db.execute(
        stmt.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    items = [
        user_vo(user, await get_role_codes(db, str(user.id))) for user in rows.scalars().all()
    ]
    return page_result(items, total, page, page_size)


async def replace_roles(db: AsyncSession, user_id: str, role_codes: list[str]) -> list[str]:
    await find_user_or_throw(db, user_id)
    rows = await db.execute(
        select(Role).where(Role.role_code.in_(role_codes), Role.status == 1)
    )
    roles = list(rows.scalars().all())
    if len(roles) != len(role_codes):
        found = {role.role_code for role in roles}
        missing = [code for code in role_codes if code not in found]
        raise not_found("角色不存在: " + ", ".join(missing))

    existing = await db.execute(select(UserRole).where(UserRole.user_id == int(user_id)))
    for row in existing.scalars().all():
        await db.delete(row)
    await db.flush()
    for role in roles:
        db.add(UserRole(id=next_id(), user_id=int(user_id), role_id=role.id))
    await db.commit()
    return role_codes


async def assign_role(db: AsyncSession, user_id: str, role_code: str) -> None:
    result = await db.execute(select(Role).where(Role.role_code == role_code))
    role = result.scalar_one_or_none()
    if role is None:
        raise not_found(f"角色 {role_code} 不存在")
    exists = await db.execute(
        select(UserRole).where(
            UserRole.user_id == int(user_id), UserRole.role_id == role.id
        )
    )
    if exists.scalar_one_or_none() is None:
        db.add(UserRole(id=next_id(), user_id=int(user_id), role_id=role.id))
        await db.commit()


async def get_user_role_codes(db: AsyncSession, user_id: str) -> list[str]:
    await find_user_or_throw(db, user_id)
    return await get_role_codes(db, user_id)


async def update_profile(
    db: AsyncSession,
    user_id: str,
    email: str | None,
    real_name: str | None,
    avatar: str | None,
) -> dict[str, Any]:
    user = await find_user_or_throw(db, user_id)
    if email is not None:
        user.email = email
    if real_name is not None:
        user.real_name = real_name
    if avatar is not None:
        user.avatar = avatar
    user.updated_at = datetime.now()
    await db.commit()
    return await get_user_vo(db, user_id)


async def change_password(
    db: AsyncSession, user_id: str, old_password: str, new_password: str
) -> None:
    user = await find_user_or_throw(db, user_id)
    if not verify_password(old_password, user.password):
        raise bad_request("原密码错误")
    user.password = hash_password(new_password)
    user.updated_at = datetime.now()
    await db.commit()


async def reset_password(db: AsyncSession, user_id: str, new_password: str) -> None:
    user = await find_user_or_throw(db, user_id)
    user.password = hash_password(new_password)
    user.updated_at = datetime.now()
    await db.commit()


async def reset_password_by_email(db: AsyncSession, email: str, new_password: str) -> None:
    user = await find_by_email(db, email)
    if user is None:
        raise not_found("该邮箱未注册")
    user.password = hash_password(new_password)
    user.updated_at = datetime.now()
    await db.commit()


async def activate_email(db: AsyncSession, user_id: str) -> str:
    user = await find_user_or_throw(db, user_id)
    if user.email_verified == 1:
        return "账户已激活，请直接登录"
    user.email_verified = 1
    user.status = 1
    await db.commit()
    return "账户激活成功，请登录"


async def get_user_statistics(db: AsyncSession, user_id: str) -> dict[str, int]:
    await find_user_or_throw(db, user_id)
    uid = int(user_id)
    count = (
        await db.execute(
            select(func.count()).select_from(Document).where(
                Document.author_id == uid, Document.deleted.is_(False)
            )
        )
    ).scalar_one()
    sums = (
        await db.execute(
            select(
                func.coalesce(func.sum(Document.view_count), 0),
                func.coalesce(func.sum(Document.like_count), 0),
                func.coalesce(func.sum(Document.comment_count), 0),
            ).where(Document.author_id == uid, Document.deleted.is_(False))
        )
    ).one()
    return {
        "documentCount": int(count),
        "viewCount": int(sums[0] or 0),
        "likeCount": int(sums[1] or 0),
        "commentCount": int(sums[2] or 0),
    }


# ---------------------------------------------------------------- 角色


def role_vo(role: Role, with_status: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(role.id),
        "roleName": role.role_name,
        "roleCode": role.role_code,
        "description": role.description,
    }
    if with_status:
        data["status"] = role.status
    return data


async def list_roles(db: AsyncSession) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(Role).where(Role.status == 1).order_by(Role.role_name.asc())
    )
    return [role_vo(role) for role in rows.scalars().all()]


async def get_role_or_throw(db: AsyncSession, role_id: str) -> Role:
    result = await db.execute(select(Role).where(Role.id == int(role_id)))
    role = result.scalar_one_or_none()
    if role is None:
        raise not_found("角色不存在")
    return role


async def create_role(
    db: AsyncSession, role_name: str, role_code: str, description: str | None
) -> dict[str, Any]:
    exists = await db.execute(select(Role).where(Role.role_code == role_code))
    if exists.scalar_one_or_none() is not None:
        raise conflict("角色编码已存在")
    role = Role(
        id=next_id(),
        role_name=role_name,
        role_code=role_code,
        description=description,
        status=1,
    )
    db.add(role)
    await db.commit()
    return role_vo(role)


async def update_role(
    db: AsyncSession,
    role_id: str,
    role_name: str | None,
    description: str | None,
    status: int | None,
) -> dict[str, Any]:
    role = await get_role_or_throw(db, role_id)
    if role_name is not None:
        role.role_name = role_name
    if description is not None:
        role.description = description
    if status is not None:
        role.status = status
    await db.commit()
    return role_vo(role, with_status=True)


async def delete_role(db: AsyncSession, role_id: str) -> None:
    role = await get_role_or_throw(db, role_id)
    bound = (
        await db.execute(
            select(func.count()).select_from(UserRole).where(UserRole.role_id == role.id)
        )
    ).scalar_one()
    if bound > 0:
        raise bad_request("角色仍有关联用户，无法删除")
    await db.delete(role)
    await db.commit()


# ---------------------------------------------------------------- 权限


def permission_vo(permission: Permission) -> dict[str, Any]:
    return {
        "id": str(permission.id),
        "parentId": str(permission.parent_id),
        "permissionName": permission.permission_name,
        "permissionCode": permission.permission_code,
        "permissionType": permission.permission_type,
        "menuUrl": permission.menu_url,
        "apiUrl": permission.api_url,
        "method": permission.method,
        "icon": permission.icon,
        "sort": permission.sort,
        "status": permission.status,
        "createdAt": iso(permission.created_at),
        "updatedAt": iso(permission.updated_at),
    }


async def list_permissions(db: AsyncSession) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(Permission)
        .where(Permission.deleted.is_(False), Permission.status == 1)
        .order_by(Permission.sort.asc(), Permission.created_at.asc())
    )
    return [permission_vo(item) for item in rows.scalars().all()]


async def get_permission_or_throw(db: AsyncSession, permission_id: str) -> Permission:
    result = await db.execute(
        select(Permission).where(
            Permission.id == int(permission_id), Permission.deleted.is_(False)
        )
    )
    permission = result.scalar_one_or_none()
    if permission is None:
        raise not_found("权限不存在")
    return permission


async def get_permission(db: AsyncSession, permission_id: str) -> dict[str, Any]:
    return permission_vo(await get_permission_or_throw(db, permission_id))


async def get_children(db: AsyncSession, parent_id: str) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(Permission)
        .where(
            Permission.parent_id == int(parent_id),
            Permission.deleted.is_(False),
            Permission.status == 1,
        )
        .order_by(Permission.sort.asc())
    )
    return [permission_vo(item) for item in rows.scalars().all()]


async def create_permission(
    db: AsyncSession, dto: CreatePermissionDto
) -> dict[str, Any]:
    exists = await db.execute(
        select(Permission).where(
            Permission.permission_code == dto.permission_code,
            Permission.deleted.is_(False),
        )
    )
    if exists.scalar_one_or_none() is not None:
        raise conflict("权限编码已存在")
    permission = Permission(
        id=next_id(),
        parent_id=int(dto.parent_id) if dto.parent_id else 0,
        permission_name=dto.permission_name,
        permission_code=dto.permission_code,
        permission_type=dto.permission_type,
        menu_url=dto.menu_url,
        api_url=dto.api_url,
        method=dto.method,
        icon=dto.icon,
        sort=dto.sort if dto.sort is not None else 0,
        status=dto.status if dto.status is not None else 1,
    )
    db.add(permission)
    await db.commit()
    return permission_vo(permission)


async def update_permission(
    db: AsyncSession, permission_id: str, dto: UpdatePermissionDto
) -> dict[str, Any]:
    permission = await get_permission_or_throw(db, permission_id)
    if dto.permission_code and dto.permission_code != permission.permission_code:
        exists = await db.execute(
            select(Permission).where(
                Permission.permission_code == dto.permission_code,
                Permission.deleted.is_(False),
            )
        )
        if exists.scalar_one_or_none() is not None:
            raise conflict("权限编码已存在")
        permission.permission_code = dto.permission_code
    if dto.permission_name is not None:
        permission.permission_name = dto.permission_name
    if dto.permission_type is not None:
        permission.permission_type = dto.permission_type
    if dto.parent_id is not None:
        if dto.parent_id == permission_id:
            raise bad_request("父权限不能是自己")
        permission.parent_id = int(dto.parent_id)
    if dto.menu_url is not None:
        permission.menu_url = dto.menu_url
    if dto.api_url is not None:
        permission.api_url = dto.api_url
    if dto.method is not None:
        permission.method = dto.method
    if dto.icon is not None:
        permission.icon = dto.icon
    if dto.sort is not None:
        permission.sort = dto.sort
    if dto.status is not None:
        permission.status = dto.status
    permission.updated_at = datetime.now()
    await db.commit()
    return permission_vo(permission)


async def delete_permission(db: AsyncSession, permission_id: str) -> None:
    permission = await get_permission_or_throw(db, permission_id)
    child_count = (
        await db.execute(
            select(func.count())
            .select_from(Permission)
            .where(
                Permission.parent_id == int(permission_id),
                Permission.deleted.is_(False),
            )
        )
    ).scalar_one()
    if child_count > 0:
        raise bad_request("存在子权限，无法删除")
    role_bound = (
        await db.execute(
            select(func.count())
            .select_from(RolePermission)
            .where(RolePermission.permission_id == permission.id)
        )
    ).scalar_one()
    user_bound = (
        await db.execute(
            select(func.count())
            .select_from(UserPermission)
            .where(UserPermission.permission_id == permission.id)
        )
    ).scalar_one()
    if role_bound > 0 or user_bound > 0:
        raise bad_request("权限仍有关联角色或用户，无法删除")
    permission.deleted = True
    await db.commit()


async def page_permissions(
    db: AsyncSession, keyword: str | None, page: int, page_size: int
) -> dict[str, Any]:
    stmt = select(Permission).where(Permission.deleted.is_(False))
    if keyword and keyword.strip():
        kw = f"%{keyword.strip()}%"
        stmt = stmt.where(
            or_(
                Permission.permission_name.ilike(kw),
                Permission.permission_code.ilike(kw),
            )
        )
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = await db.execute(
        stmt.order_by(Permission.sort.asc(), Permission.created_at.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return page_result(
        [permission_vo(item) for item in rows.scalars().all()], total, page, page_size
    )


async def permission_tree(db: AsyncSession) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(Permission)
        .where(Permission.deleted.is_(False), Permission.status == 1)
        .order_by(Permission.sort.asc(), Permission.created_at.asc())
    )
    items = list(rows.scalars().all())

    def build(parent_id: str) -> list[dict[str, Any]]:
        result = []
        for item in items:
            if str(item.parent_id) == parent_id:
                node = permission_vo(item)
                node["children"] = build(str(item.id))
                result.append(node)
        return result

    return build("0")


async def ensure_role_exists(db: AsyncSession, role_id: str) -> None:
    await get_role_or_throw(db, role_id)


async def get_role_permission_ids(db: AsyncSession, role_id: str) -> list[str]:
    await ensure_role_exists(db, role_id)
    rows = await db.execute(
        select(RolePermission.permission_id).where(RolePermission.role_id == int(role_id))
    )
    return [str(row[0]) for row in rows.all()]


async def validate_permission_ids(db: AsyncSession, ids: list[str]) -> None:
    if not ids:
        return
    rows = await db.execute(
        select(Permission).where(
            Permission.id.in_([int(item) for item in ids]),
            Permission.deleted.is_(False),
            Permission.status == 1,
        )
    )
    if len(list(rows.scalars().all())) != len(ids):
        raise not_found("部分权限不存在或已禁用")


async def assign_role_permissions(
    db: AsyncSession, role_id: str, dto: AssignPermissionIdsDto
) -> list[str]:
    await ensure_role_exists(db, role_id)
    await validate_permission_ids(db, dto.permission_ids)
    rows = await db.execute(
        select(RolePermission).where(RolePermission.role_id == int(role_id))
    )
    for row in rows.scalars().all():
        await db.delete(row)
    await db.flush()
    for permission_id in dto.permission_ids:
        db.add(
            RolePermission(
                id=next_id(),
                role_id=int(role_id),
                permission_id=int(permission_id),
            )
        )
    await db.commit()
    return dto.permission_ids


async def get_user_direct_permission_ids(db: AsyncSession, user_id: str) -> list[str]:
    rows = await db.execute(
        select(UserPermission.permission_id).where(UserPermission.user_id == int(user_id))
    )
    return [str(row[0]) for row in rows.all()]


async def assign_user_permissions(
    db: AsyncSession, user_id: str, dto: AssignPermissionIdsDto
) -> list[str]:
    await find_user_or_throw(db, user_id)
    await validate_permission_ids(db, dto.permission_ids)
    rows = await db.execute(
        select(UserPermission).where(UserPermission.user_id == int(user_id))
    )
    for row in rows.scalars().all():
        await db.delete(row)
    await db.flush()
    for permission_id in dto.permission_ids:
        db.add(
            UserPermission(
                id=next_id(),
                user_id=int(user_id),
                permission_id=int(permission_id),
            )
        )
    await db.commit()
    return dto.permission_ids


# ---------------------------------------------------------------- 团队


def team_vo(team: Team, **extra: Any) -> dict[str, Any]:
    data = {
        "id": str(team.id),
        "teamName": team.team_name,
        "teamCode": team.team_code,
        "description": team.description,
        "leaderId": str(team.leader_id) if team.leader_id else None,
        "parentId": str(team.parent_id),
        "sort": team.sort,
        "status": team.status,
        "createdAt": iso(team.created_at),
        "updatedAt": iso(team.updated_at),
    }
    data.update(extra)
    return data


async def list_mine(db: AsyncSession, user_id: str) -> list[dict[str, Any]]:
    ids = await list_accessible_team_ids(db, user_id)
    if not ids:
        return []
    rows = await db.execute(
        select(Team)
        .where(Team.id.in_([int(item) for item in ids]), Team.deleted.is_(False))
        .order_by(Team.sort.asc(), Team.created_at.asc())
    )
    return [team_vo(team) for team in rows.scalars().all()]


async def create_team(db: AsyncSession, dto: CreateTeamDto) -> dict[str, Any]:
    team = Team(
        id=next_id(),
        team_name=dto.team_name,
        team_code=dto.team_code,
        description=dto.description,
        leader_id=int(dto.leader_id) if dto.leader_id else None,
        parent_id=int(dto.parent_id) if dto.parent_id else 0,
        sort=dto.sort if dto.sort is not None else 0,
        status=dto.status if dto.status is not None else 1,
    )
    db.add(team)
    await db.commit()
    return team_vo(team)


async def find_team_or_throw(db: AsyncSession, team_id: str) -> Team:
    result = await db.execute(
        select(Team).where(Team.id == int(team_id), Team.deleted.is_(False))
    )
    team = result.scalar_one_or_none()
    if team is None:
        raise not_found("团队不存在")
    return team


async def update_team(db: AsyncSession, team_id: str, dto: UpdateTeamDto) -> dict[str, Any]:
    team = await find_team_or_throw(db, team_id)
    if dto.team_name is not None:
        team.team_name = dto.team_name
    if dto.team_code is not None:
        team.team_code = dto.team_code
    if dto.description is not None:
        team.description = dto.description
    if dto.leader_id is not None:
        team.leader_id = int(dto.leader_id)
    if dto.parent_id is not None:
        if dto.parent_id == team_id:
            raise bad_request("父团队不能是自己")
        team.parent_id = int(dto.parent_id)
    if dto.sort is not None:
        team.sort = dto.sort
    if dto.status is not None:
        team.status = dto.status
    team.updated_at = datetime.now()
    await db.commit()
    return team_vo(team)


async def delete_team(db: AsyncSession, team_id: str) -> None:
    team = await find_team_or_throw(db, team_id)
    child_count = (
        await db.execute(
            select(func.count())
            .select_from(Team)
            .where(Team.parent_id == int(team_id), Team.deleted.is_(False))
        )
    ).scalar_one()
    if child_count > 0:
        raise bad_request("存在子团队，无法删除")
    team.deleted = True
    rows = await db.execute(select(TeamMember).where(TeamMember.team_id == int(team_id)))
    for row in rows.scalars().all():
        await db.delete(row)
    await db.commit()


async def get_team_detail(db: AsyncSession, team_id: str) -> dict[str, Any]:
    team = await find_team_or_throw(db, team_id)
    member_count = (
        await db.execute(
            select(func.count())
            .select_from(TeamMember)
            .where(TeamMember.team_id == int(team_id))
        )
    ).scalar_one()
    return team_vo(team, memberCount=int(member_count))


async def page_teams(
    db: AsyncSession,
    keyword: str | None,
    status: int | None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    stmt = select(Team).where(Team.deleted.is_(False))
    if keyword and keyword.strip():
        kw = f"%{keyword.strip()}%"
        stmt = stmt.where(or_(Team.team_name.ilike(kw), Team.team_code.ilike(kw)))
    if status is not None:
        stmt = stmt.where(Team.status == status)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = await db.execute(
        stmt.order_by(Team.sort.asc(), Team.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return page_result(
        [team_vo(team) for team in rows.scalars().all()], total, page, page_size
    )


async def team_tree(db: AsyncSession, root_only: bool = False) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(Team)
        .where(Team.deleted.is_(False), Team.status == 1)
        .order_by(Team.sort.asc(), Team.created_at.asc())
    )
    teams = list(rows.scalars().all())

    def build(parent_id: str) -> list[dict[str, Any]]:
        result = []
        for team in teams:
            if str(team.parent_id) == parent_id:
                node = team_vo(team)
                node["children"] = [] if root_only else build(str(team.id))
                result.append(node)
        return result

    roots = [team_vo(team) for team in teams if str(team.parent_id) in ("", "0")]
    if root_only:
        return roots
    for node in roots:
        node["children"] = build(node["id"])
    return roots


async def add_team_members(db: AsyncSession, team_id: str, user_ids: list[str]) -> bool:
    await find_team_or_throw(db, team_id)
    rows = await db.execute(
        select(User).where(
            User.id.in_([int(item) for item in user_ids]), User.deleted.is_(False)
        )
    )
    users = list(rows.scalars().all())
    if len(users) != len(user_ids):
        raise not_found("部分用户不存在")
    for user_id in user_ids:
        exists = await db.execute(
            select(TeamMember).where(
                TeamMember.team_id == int(team_id),
                TeamMember.user_id == int(user_id),
            )
        )
        if exists.scalar_one_or_none() is not None:
            continue
        db.add(
            TeamMember(
                id=next_id(),
                team_id=int(team_id),
                user_id=int(user_id),
                member_role="member",
            )
        )
    await db.commit()
    return True


async def remove_team_members(db: AsyncSession, team_id: str, user_ids: list[str]) -> bool:
    await find_team_or_throw(db, team_id)
    rows = await db.execute(
        select(TeamMember).where(
            TeamMember.team_id == int(team_id),
            TeamMember.user_id.in_([int(item) for item in user_ids]),
        )
    )
    for row in rows.scalars().all():
        await db.delete(row)
    await db.commit()
    return True


async def list_team_members(db: AsyncSession, team_id: str) -> list[dict[str, Any]]:
    await find_team_or_throw(db, team_id)
    rows = await db.execute(
        select(TeamMember.user_id, TeamMember.member_role, User.username, User.real_name)
        .join(User, User.id == TeamMember.user_id)
        .where(TeamMember.team_id == int(team_id), User.deleted.is_(False))
    )
    return [
        {
            "userId": str(row[0]),
            "memberRole": row[1],
            "username": row[2],
            "realName": row[3],
        }
        for row in rows.all()
    ]


__all__ = [name for name in dir() if not name.startswith("_")]
