"""Authentication / authorization dependencies (deny-by-default)."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.errors import AuthError, ForbiddenError
from app.core.permissions import permissions_for_roles
from app.core.security import decode_access_token
from app.models import User


def _bearer_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise AuthError("Authentication required")
    token = auth[len("Bearer ") :].strip()
    if not token:
        raise AuthError("Authentication required")
    return token


def get_current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    token = _bearer_token(request)
    payload = decode_access_token(token)
    user = db.execute(
        select(User).options(joinedload(User.roles)).where(User.id == int(payload["sub"]))
    ).unique().scalar_one_or_none()
    if user is None:
        raise AuthError("User no longer exists")
    if not user.is_active:
        raise AuthError("Account is deactivated")
    request.state.user_id = user.id
    request.state.user_email = user.email
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def user_role_names(user: User) -> set[str]:
    return {r.name for r in user.roles}


def user_permissions(user: User) -> set[str]:
    return permissions_for_roles(user_role_names(user))


def require_permissions(*needed: str) -> Callable[..., set[str]]:
    """Dependency factory: grants access only when every permission is held."""

    def _dep(user: CurrentUser) -> set[str]:
        perms = user_permissions(user)
        granted = "*" in perms
        missing = [] if granted else [p for p in needed if p not in perms]
        if missing:
            raise ForbiddenError(
                f"Missing permission: {', '.join(missing)}",
                details={"required": list(needed), "missing": missing},
            )
        return perms

    return _dep


def assert_permissions(user: User, needed: Iterable[str]) -> None:
    """Imperative variant used inside services."""
    perms = user_permissions(user)
    if "*" in perms:
        return
    missing = [p for p in needed if p not in perms]
    if missing:
        raise ForbiddenError(f"Missing permission: {', '.join(missing)}", details={"missing": missing})
