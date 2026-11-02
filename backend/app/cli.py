"""Small operational CLI.

Usage (from ``backend/``)::

    python -m app.cli create-tables
    python -m app.cli bootstrap
    python -m app.cli bootstrap-admin --email admin@example.org --name "Admin"
    python -m app.cli run-job 42
    python -m app.cli worker
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
import time

from sqlalchemy import select

from app.core.config import settings
from app.core.database import engine, session_scope
from app.core.permissions import SUPER_ADMIN
from app.core.security import hash_password
from app.models import Base, Role, User, utcnow
from app.services import handlers  # noqa: F401  (registers handlers)
from app.services.bootstrap import run_bootstrap
from app.services.jobs import execute_job_now, start_workers, stop_workers
from app.services.storage import ensure_storage_dirs


def _bootstrap_admin(email: str, password: str, name: str) -> None:
    with session_scope() as db:
        Base.metadata.create_all(bind=engine)
        run_bootstrap(db)
        existing = db.execute(select(User).where(User.email == email.strip().lower())).scalar_one_or_none()
        if existing is not None:
            print(f"User {email} already exists (id={existing.id}); nothing to do.")
            return
        role = db.execute(select(Role).where(Role.name == SUPER_ADMIN)).scalar_one()
        user = User(
            email=email.strip().lower(),
            full_name=name.strip(),
            hashed_password=hash_password(password),
            is_active=True,
            roles=[role],
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(user)
        db.flush()
        print(f"Created Super Administrator {user.email} (id={user.id}).")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="LakeWatch operations")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("create-tables", help="Create missing tables from SQLAlchemy metadata")
    sub.add_parser("bootstrap", help="Seed roles/permissions, default study area and indicators")

    admin = sub.add_parser("bootstrap-admin", help="Create a Super Administrator")
    admin.add_argument("--email", default=os.getenv("BOOTSTRAP_ADMIN_EMAIL") or settings.bootstrap_admin_email)
    admin.add_argument("--password", default=os.getenv("BOOTSTRAP_ADMIN_PASSWORD") or settings.bootstrap_admin_password)
    admin.add_argument("--name", default=os.getenv("BOOTSTRAP_ADMIN_NAME") or settings.bootstrap_admin_name or "System Administrator")

    run = sub.add_parser("run-job", help="Run one queued job synchronously")
    run.add_argument("job_id", type=int)

    worker = sub.add_parser("worker", help="Run background workers in the foreground")
    worker.add_argument("--poll", type=float, default=settings.jobs_poll_interval_seconds)

    args = parser.parse_args(argv)
    ensure_storage_dirs()

    if args.command == "create-tables":
        Base.metadata.create_all(bind=engine)
        print("Tables created.")
        return 0

    if args.command == "bootstrap":
        with session_scope() as db:
            run_bootstrap(db)
        print("Bootstrap complete.")
        return 0

    if args.command == "bootstrap-admin":
        email = args.email
        password = args.password
        if not email:
            email = input("Admin email: ").strip()
        if not password:
            password = getpass.getpass("Admin password (min 10 chars): ")
        if len(password) < 10:
            print("Password must be at least 10 characters.", file=sys.stderr)
            return 2
        if not email:
            print("Email is required.", file=sys.stderr)
            return 2
        _bootstrap_admin(email, password, args.name)
        return 0

    if args.command == "run-job":
        with session_scope() as db:
            job = execute_job_now(db, args.job_id)
            print(f"Job {job.id} status={job.status} error={job.error}")
        return 0 if job.status == "succeeded" else 1

    if args.command == "worker":
        start_workers()
        print("Workers started; press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            stop_workers()
        return 0

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
