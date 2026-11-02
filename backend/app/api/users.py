"""Admin: user account and role management."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.serializers import page_response
from app.core.database import get_db
from app.core.deps import CurrentUser, require_permissions
from app.core.permissions import PERMISSIONS
from app.models import Permission, Role
from app.schemas.admin import (
    PasswordResetOut,
    RoleOut,
    UserCreate,
    UserOut,
    UserRolesUpdate,
    UserUpdate,
)
from app.schemas.common import Page
from app.services import users as user_service

router = APIRouter(prefix="/admin", tags=["admin: users"])

ReadUsers = Annotated[set[str], Depends(require_permissions("admin.users.read"))]
WriteUsers = Annotated[set[str], Depends(require_permissions("admin.users.write"))]
ReadRoles = Annotated[set[str], Depends(require_permissions("admin.roles.read"))]


@router.get("/users", response_model=Page[UserOut])
def list_users(
    _perms: ReadUsers,
    db: Annotated[Session, Depends(get_db)],
    search: str | None = None,
    role: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    sort: str = "created_at",
    direction: str = Query("desc", pattern="^(asc|desc)$"),
) -> Page[UserOut]:
    rows, total = user_service.list_users(
        db,
        search=search,
        role=role,
        status=status_filter,
        page=page,
        size=size,
        sort=sort,
        direction=direction,
    )
    return page_response([UserOut.from_user(u) for u in rows], total, page, size)


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    user: CurrentUser,
    _perms: WriteUsers,
    db: Annotated[Session, Depends(get_db)],
) -> UserOut:
    created = user_service.create_user(db, payload=payload, actor=user)
    db.commit()
    db.refresh(created)
    return UserOut.from_user(created)


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(
    user_id: int,
    _perms: ReadUsers,
    db: Annotated[Session, Depends(get_db)],
) -> UserOut:
    return UserOut.from_user(user_service.get_user(db, user_id))


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    actor: CurrentUser,
    _perms: WriteUsers,
    db: Annotated[Session, Depends(get_db)],
) -> UserOut:
    target = user_service.get_user(db, user_id)
    updated = user_service.update_user(db, payload=payload, actor=actor, target=target)
    db.commit()
    db.refresh(updated)
    return UserOut.from_user(updated)


@router.post("/users/{user_id}/activate", response_model=UserOut)
def activate_user(
    user_id: int,
    actor: CurrentUser,
    _perms: WriteUsers,
    db: Annotated[Session, Depends(get_db)],
) -> UserOut:
    target = user_service.get_user(db, user_id)
    updated = user_service.set_active(db, target=target, active=True, actor=actor)
    db.commit()
    db.refresh(updated)
    return UserOut.from_user(updated)


@router.post("/users/{user_id}/deactivate", response_model=UserOut)
def deactivate_user(
    user_id: int,
    actor: CurrentUser,
    _perms: WriteUsers,
    db: Annotated[Session, Depends(get_db)],
) -> UserOut:
    target = user_service.get_user(db, user_id)
    updated = user_service.set_active(db, target=target, active=False, actor=actor)
    db.commit()
    db.refresh(updated)
    return UserOut.from_user(updated)


@router.put("/users/{user_id}/roles", response_model=UserOut)
def set_user_roles(
    user_id: int,
    payload: UserRolesUpdate,
    actor: CurrentUser,
    _perms: WriteUsers,
    db: Annotated[Session, Depends(get_db)],
) -> UserOut:
    target = user_service.get_user(db, user_id)
    updated = user_service.set_roles(db, target=target, role_names=payload.roles, actor=actor)
    db.commit()
    db.refresh(updated)
    return UserOut.from_user(updated)


@router.post("/users/{user_id}/password-reset", response_model=PasswordResetOut)
def issue_password_reset(
    user_id: int,
    actor: CurrentUser,
    _perms: WriteUsers,
    db: Annotated[Session, Depends(get_db)],
) -> PasswordResetOut:
    target = user_service.get_user(db, user_id)
    token, expires = user_service.create_password_reset(db, target=target)
    db.commit()
    from app.services import audit as audit_service

    audit_service.record(
        action="user.password_reset_issue",
        resource_type="user",
        resource_id=target.id,
        actor=actor,
        message=f"Issued a one-time password reset token for {target.email}",
        details={"expires_at": expires.isoformat()},
    )
    return PasswordResetOut(reset_token=token, expires_at=expires)


# --------------------------------------------------------------------- roles
@router.get("/roles", response_model=list[RoleOut])
def list_roles(
    _perms: ReadRoles,
    db: Annotated[Session, Depends(get_db)],
) -> list[RoleOut]:
    rows = db.execute(select(Role).order_by(Role.id.asc())).unique().scalars().all()
    return [
        RoleOut(
            id=r.id,
            name=r.name,
            description=r.description,
            permissions=sorted(r.permission_keys()),
        )
        for r in rows
    ]


@router.get("/permissions")
def list_permissions(
    _perms: ReadRoles,
    db: Annotated[Session, Depends(get_db)],
) -> list[dict]:
    rows = db.execute(select(Permission).order_by(Permission.key.asc())).scalars().all()
    return [
        {"key": p.key, "description": p.description, "module": p.module}
        for p in rows
        if p.key in PERMISSIONS
    ]
