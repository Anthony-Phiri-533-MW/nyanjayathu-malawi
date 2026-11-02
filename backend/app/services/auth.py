"""Authentication: login, token issuance, password changes."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.errors import AuthError
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User, utcnow
from app.services import audit as audit_service
from app.services.users import get_user_by_email


def _client_ip(request) -> str | None:
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:60]
    return request.client.host if request.client else None


def login(db: Session, *, email: str, password: str, request=None) -> tuple[str, User, int]:
    user = get_user_by_email(db, email)
    ip = _client_ip(request)
    valid = user is not None and verify_password(password, user.hashed_password)

    if not valid:
        audit_service.record(
            action="auth.login",
            resource_type="user",
            resource_id=user.id if user else None,
            outcome="failure",
            actor_id=user.id if user else None,
            actor_email=email.strip().lower(),
            message="Failed login attempt",
            ip_address=ip,
            details={"reason": "invalid_credentials"},
        )
        # Same error for unknown user and wrong password (no account enumeration).
        raise AuthError("Invalid email or password")

    assert user is not None
    if not user.is_active:
        audit_service.record(
            action="auth.login",
            resource_type="user",
            resource_id=user.id,
            outcome="failure",
            actor=user,
            message="Login attempt on deactivated account",
            ip_address=ip,
            details={"reason": "account_deactivated"},
        )
        raise AuthError("Account is deactivated. Contact an administrator.")

    now = datetime.now(UTC).replace(tzinfo=None)
    user.last_login_at = now
    db.commit()

    role_names = user.role_names()
    from app.core.config import settings

    token = create_access_token(subject=str(user.id), role_names=role_names)
    audit_service.record(
        action="auth.login",
        resource_type="user",
        resource_id=user.id,
        outcome="success",
        actor=user,
        message=f"{user.email} signed in",
        ip_address=ip,
        details={"roles": sorted(role_names)},
    )
    return token, user, settings.access_token_expire_minutes


def change_own_password(
    db: Session, *, user: User, current_password: str, new_password: str
) -> None:
    if not verify_password(current_password, user.hashed_password):
        audit_service.record(
            action="auth.password_change",
            resource_type="user",
            resource_id=user.id,
            outcome="failure",
            actor=user,
            message="Current password did not match",
        )
        raise AuthError("Current password is incorrect")
    user.hashed_password = hash_password(new_password)
    user.updated_at = utcnow()
    db.commit()
    audit_service.record(
        action="auth.password_change",
        resource_type="user",
        resource_id=user.id,
        outcome="success",
        actor=user,
        message="Password changed by owner",
    )
