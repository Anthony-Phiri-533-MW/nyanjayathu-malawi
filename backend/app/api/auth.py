"""Authentication endpoints."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import CurrentUser
from app.schemas.admin import (
    LoginRequest,
    MeOut,
    PasswordChange,
    PasswordResetConfirm,
    PasswordResetRequest,
    TokenResponse,
    UserOut,
)
from app.schemas.common import Message
from app.services import audit as audit_service
from app.services import auth as auth_service
from app.services import users as user_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> TokenResponse:
    token, _user, minutes = auth_service.login(
        db, email=str(payload.email), password=payload.password, request=request
    )
    return TokenResponse(access_token=token, token_type="bearer", expires_in_minutes=minutes)


@router.get("/me", response_model=MeOut)
def me(user: CurrentUser) -> MeOut:
    return MeOut(**UserOut.from_user(user).model_dump())


@router.post("/change-password", response_model=Message)
def change_password(
    payload: PasswordChange,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> Message:
    auth_service.change_own_password(
        db,
        user=user,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    return Message(message="Password changed")


@router.post("/password-reset/request", response_model=Message, status_code=status.HTTP_202_ACCEPTED)
def request_password_reset(
    payload: PasswordResetRequest,
    db: Annotated[Session, Depends(get_db)],
) -> Message:
    """Record a reset request.  This deployment has no mail provider, so the
    token is issued by an administrator (Admin > Users > Reset password)."""
    target = user_service.get_user_by_email(db, str(payload.email))
    audit_service.record(
        action="auth.password_reset_request",
        resource_type="user",
        resource_id=target.id if target else None,
        actor_id=target.id if target else None,
        actor_email=str(payload.email).strip().lower(),
        outcome="success",
        message="Password reset requested (token must be issued by an administrator)",
        details={"account_exists": target is not None},
    )
    # Same response whether or not the account exists (no enumeration).
    return Message(
        message="If the account exists, contact an administrator to issue a one-time reset token."
    )


@router.post("/password-reset/confirm", response_model=Message)
def confirm_password_reset(
    payload: PasswordResetConfirm,
    db: Annotated[Session, Depends(get_db)],
) -> Message:
    user = user_service.reset_password_with_token(
        db, token=payload.token, new_password=payload.new_password
    )
    db.commit()
    audit_service.record(
        action="auth.password_reset",
        resource_type="user",
        resource_id=user.id,
        actor=user,
        message="Password reset completed with a one-time token",
    )
    return Message(message="Password has been reset; sign in with the new password")
