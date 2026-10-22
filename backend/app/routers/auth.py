from fastapi import APIRouter, Depends, Query

from app.core.deps import CurrentUser, DbSession, require_roles
from app.schemas.auth import LoginDto, RefreshTokenDto, RegisterDto, ResetPasswordByEmailDto, SendResetCodeDto
from app.services import accounts, auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register")
async def register(db: DbSession, dto: RegisterDto):
    return await auth_service.register(db, dto)


@router.post("/login")
async def login(db: DbSession, dto: LoginDto):
    return await auth_service.login(db, dto)


@router.post("/refresh")
async def refresh(db: DbSession, dto: RefreshTokenDto):
    return await auth_service.refresh(db, dto.refresh_token)


@router.get("/verify-email")
async def verify_email(db: DbSession, token: str = Query(...)):
    return await auth_service.verify_email(db, token)


@router.post("/password/reset/send-code")
async def send_reset_code(db: DbSession, dto: SendResetCodeDto):
    return await auth_service.send_reset_code(db, dto)


@router.post("/password/reset")
async def reset_password(db: DbSession, dto: ResetPasswordByEmailDto):
    return await auth_service.reset_password_by_email(db, dto)


@router.post("/logout")
async def logout(_: CurrentUser):
    return {"message": "已退出登录"}


@router.get("/me")
async def me(user: CurrentUser):
    return user.to_dict()


@router.get(
    "/reviewer-ids",
    dependencies=[Depends(require_roles(accounts.ROLE_ADMIN, accounts.ROLE_REVIEWER))],
)
async def reviewer_ids(db: DbSession):
    return await accounts.get_user_ids_by_role_code(db, accounts.ROLE_REVIEWER)
