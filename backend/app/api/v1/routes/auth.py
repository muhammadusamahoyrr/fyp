from fastapi import APIRouter, Request, Response

from app.core.exceptions import AuthError
from app.core.rate_limit import limiter
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    RefreshResponse,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
)
from app.schemas.common import StatusResponse
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=StatusResponse)
@limiter.limit("5/minute")
async def register(request: Request, body: RegisterRequest):
    await auth_service.register(body)
    return StatusResponse(success=True, message="Account created successfully")


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, body: LoginRequest, response: Response):
    result = await auth_service.login(body.email, body.password)
    response.set_cookie(
        key="refresh_token",
        value=result["refresh_token"],
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=7 * 24 * 3600,
    )
    return TokenResponse(
        access_token=result["access_token"],
        role=result["role"],
        user_id=result["user_id"],
    )


@router.post("/refresh", response_model=RefreshResponse)
@limiter.limit("20/minute")
async def refresh(request: Request):
    token = request.cookies.get("refresh_token")
    if not token:
        raise AuthError("Refresh token missing")
    access_token = await auth_service.refresh(token)
    return RefreshResponse(access_token=access_token)


@router.post("/logout", response_model=StatusResponse)
async def logout(request: Request, response: Response):
    token = request.cookies.get("refresh_token")
    if token:
        await auth_service.logout(token)
    response.delete_cookie("refresh_token")
    return StatusResponse(success=True, message="Logged out")


@router.post("/forgot-password", response_model=StatusResponse)
@limiter.limit("3/minute")
async def forgot_password(request: Request, body: ForgotPasswordRequest):
    await auth_service.forgot_password(body.email)
    return StatusResponse(
        success=True,
        message="If that email exists, a reset link has been sent",
    )


@router.post("/reset-password", response_model=StatusResponse)
@limiter.limit("5/minute")
async def reset_password(request: Request, body: ResetPasswordRequest):
    await auth_service.reset_password(body.token, body.new_password)
    return StatusResponse(success=True, message="Password updated successfully")
