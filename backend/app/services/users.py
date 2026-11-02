"""User account administration with privilege-escalation guards.

Escalation rules enforced here (backend-side, independent of the UI):

* only Super Administrators may grant or revoke the ``super_admin`` role;
* an administrator cannot modify an account that holds ``super_admin``;
* an administrator cannot grant permissions they do not themselves hold;
* administrators cannot change their own roles or activation state;
* the last active administrator cannot be deactivated or stripped of
  user-management rights.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.database import count_query
from app.core.deps import user_permissions
from app.core.errors import ConflictError, NotFoundError, UnprocessableError
from app.core.permissions import ADMIN, RESEARCHER, ROLE_ORDER, SUPER_ADMIN, permissions_for_roles
from app.core.security import hash_password, hash_token, new_reset_token
from app.models import Role, User, utcnow
from app.schemas.admin import UserCreate, UserUpdate
from app.services import audit as audit_service

RESET_TOKEN_TTL_HOURS = 24


def _base_query(db: Session):
    return select(User).options(joinedload(User.roles))


def get_user(db: Session, user_id: int) -> User:
    user = db.execute(_base_query(db).where(User.id == user_id)).unique().scalar_one_or_none()
    if user is None:
        raise NotFoundError("User not found", details={"user_id": user_id})
    return user


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.execute(
        _base_query(db).where(func.lower(User.email) == email.strip().lower())
    ).unique().scalar_one_or_none()


def _roles(db: Session, names: list[str]) -> list[Role]:
    rows = db.execute(select(Role).where(Role.name.in_(names))).scalars().all()
    found = {r.name for r in rows}
    missing = set(names) - found
    if missing:
        raise UnprocessableError(f"Unknown roles: {', '.join(sorted(missing))}")
    order = {n: i for i, n in enumerate(ROLE_ORDER)}
    return sorted(rows, key=lambda r: order.get(r.name, 99))


def role_rank(names: set[str]) -> int:
    """Highest role rank held (super=2, admin=1, researcher=0, none=-1)."""
    ranks = {SUPER_ADMIN: 2, ADMIN: 1, RESEARCHER: 0}
    return max((ranks[n] for n in names if n in ranks), default=-1)


def administrator_count(db: Session, *, exclude_id: int | None = None) -> int:
    """Active users holding ``admin.users.write`` (i.e. real administrators)."""
    users = db.execute(_base_query(db).where(User.is_active.is_(True))).unique().scalars().all()
    count = 0
    for u in users:
        if exclude_id is not None and u.id == exclude_id:
            continue
        if "admin.users.write" in user_permissions(u):
            count += 1
    return count


def _guard(actor: User, target: User, *, privileged_fields: bool) -> None:
    """Privilege and status guards.

    ``privileged_fields`` is True when the request changes roles or activation
    state.  Those changes are never self-service, and a plain administrator may
    never touch a Super Administrator account at all - not even the display
    name - because that account holds powers the administrator does not.
    """
    is_super_actor = SUPER_ADMIN in actor.role_names()
    is_super_target = SUPER_ADMIN in target.role_names()

    if target.id == actor.id and privileged_fields:
        raise ConflictError(
            "You cannot change your own roles or account status; ask another administrator"
        )
    if is_super_target and not is_super_actor:
        from app.core.errors import ForbiddenError

        raise ForbiddenError("Only a Super Administrator can modify a Super Administrator account")


def _assert_grantable(actor: User, role_names: set[str]) -> None:
    """Role ranks: researcher < admin < super_admin.

    An administrator may assign researcher and admin accounts but never the
    super_admin role; only a Super Administrator may create or grant one.
    """
    if not role_names:
        return
    max_rank = role_rank(actor.role_names())
    offenders = [r for r in role_names if role_rank({r}) > max_rank]
    if offenders:
        from app.core.errors import ForbiddenError

        raise ForbiddenError(
            "You cannot grant roles at or above your own privilege level",
            details={"roles": sorted(offenders)},
        )


def _assert_not_last_admin(db: Session, target: User, *, losing_protection: bool) -> None:
    if not losing_protection:
        return
    others = administrator_count(db, exclude_id=target.id)
    if others <= 0:
        raise ConflictError(
            "Refusing to deactivate or demote the last active administrator",
            details={"user_id": target.id},
        )


def list_users(
    db: Session,
    *,
    search: str | None = None,
    role: str | None = None,
    status: str | None = None,
    page: int = 1,
    size: int = 20,
    sort: str = "created_at",
    direction: str = "desc",
):
    stmt = _base_query(db)
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(or_(User.email.ilike(like), User.full_name.ilike(like)))
    if role:
        stmt = stmt.where(User.roles.any(Role.name == role))
    if status == "active":
        stmt = stmt.where(User.is_active.is_(True))
    elif status == "inactive":
        stmt = stmt.where(User.is_active.is_(False))

    total = count_query(stmt, db)

    sort_col = {
        "created_at": User.created_at,
        "email": User.email,
        "full_name": User.full_name,
        "last_login_at": User.last_login_at,
        "is_active": User.is_active,
    }.get(sort, User.created_at)
    order = sort_col.asc() if direction == "asc" else sort_col.desc()
    rows = db.execute(stmt.order_by(order, User.id.asc()).limit(size).offset((page - 1) * size)).unique().scalars().all()
    return list(rows), total


def create_user(db: Session, *, payload: UserCreate, actor: User) -> User:
    if get_user_by_email(db, payload.email):
        raise ConflictError("An account with this email already exists")
    _assert_grantable(actor, set(payload.roles))
    user = User(
        email=payload.email.strip().lower(),
        full_name=payload.full_name.strip(),
        hashed_password=hash_password(payload.password),
        is_active=payload.is_active,
        department=payload.department,
        created_by_id=actor.id,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    if payload.roles:
        user.roles = _roles(db, payload.roles)
    db.add(user)
    db.flush()
    audit_service.record(
        action="user.create",
        resource_type="user",
        resource_id=user.id,
        actor=actor,
        db=db,
        message=f"Created user {user.email}",
        details={
            "email": user.email,
            "roles": sorted(user.role_names()),
            "is_active": user.is_active,
            "department": user.department,
        },
    )
    return user


def update_user(db: Session, *, payload: UserUpdate, actor: User, target: User) -> User:
    # The guard applies to *every* modification, not just role/status changes:
    # a plain administrator must not be able to edit a Super Administrator
    # account (even just the display name).
    _guard(actor, target, privileged_fields=payload.roles is not None or payload.is_active is not None)
    if payload.roles is not None:
        new_roles = set(payload.roles)
        _assert_grantable(actor, new_roles)
        # losing admin rights / deactivation must not remove the last admin
        if SUPER_ADMIN not in new_roles and not (
            permissions_for_roles(new_roles) & {"admin.users.write"}
        ):
            _assert_not_last_admin(db, target, losing_protection=True)
        if new_roles != set(target.role_names()):
            target.roles = _roles(db, payload.roles)
    if payload.is_active is not None and payload.is_active is False:
        was_admin = "admin.users.write" in user_permissions(target)
        target.is_active = False
        if was_admin:
            db.flush()
            _assert_not_last_admin(db, target, losing_protection=True)
    elif payload.is_active is not None:
        target.is_active = True

    if payload.full_name is not None:
        target.full_name = payload.full_name.strip()
    if payload.department is not None:
        target.department = payload.department
    if payload.password:
        target.hashed_password = hash_password(payload.password)
        target.password_reset_hash = None
        target.password_reset_expires_at = None
    target.updated_at = utcnow()
    db.flush()
    audit_service.record(
        action="user.update",
        resource_type="user",
        resource_id=target.id,
        actor=actor,
        db=db,
        message=f"Updated user {target.email}",
        details={
            "fields": sorted(payload.model_dump(exclude_unset=True).keys()),
            "roles": sorted(target.role_names()) if payload.roles is not None else None,
            "is_active": target.is_active,
            "password_changed": bool(payload.password),
        },
    )
    return target


def set_active(db: Session, *, target: User, active: bool, actor: User) -> User:
    return update_user(db, payload=UserUpdate(is_active=active), actor=actor, target=target)


def set_roles(db: Session, *, target: User, role_names: list[str], actor: User) -> User:
    return update_user(db, payload=UserUpdate(roles=role_names), actor=actor, target=target)


def create_password_reset(db: Session, *, target: User) -> tuple[str, datetime]:
    token, digest = new_reset_token()
    expires = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=RESET_TOKEN_TTL_HOURS)
    target.password_reset_hash = digest
    target.password_reset_expires_at = expires
    target.password_reset_used_at = None
    target.updated_at = utcnow()
    db.flush()
    return token, expires


def reset_password_with_token(db: Session, *, token: str, new_password: str) -> User:
    digest = hash_token(token)
    user = db.execute(
        select(User).where(User.password_reset_hash == digest)
    ).unique().scalar_one_or_none()
    now = datetime.now(UTC).replace(tzinfo=None)
    if user is None or user.password_reset_used_at is not None:
        raise UnprocessableError("Invalid or unknown reset token")
    if user.password_reset_expires_at and user.password_reset_expires_at < now:
        raise UnprocessableError("Reset token has expired")
    user.hashed_password = hash_password(new_password)
    user.password_reset_hash = None
    user.password_reset_expires_at = None
    user.password_reset_used_at = now
    user.is_active = True
    user.updated_at = now
    db.flush()
    return user
