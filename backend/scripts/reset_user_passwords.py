#!/usr/bin/env python3
"""Bulk reset active user credentials during the argon2 password upgrade.

This script is intended for the one-time bcrypt removal rollout. It lets an
administrator export the current active user list, prepare a CSV with the new
credentials, and then apply the update while revoking existing refresh sessions.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import getpass
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, cast
from uuid import UUID

from sqlalchemy import select

# Ensure the backend package is importable when this script is executed directly.
BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.core.security import get_password_hash, validate_password_strength  # noqa: E402
from app.db.models.user import User  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.features.auth import service as auth_service  # noqa: E402
from app.features.auth.session_service import (  # noqa: E402
    revoke_all_refresh_sessions_for_user,
)


@dataclass(frozen=True)
class CredentialResetRow:
    """One requested credential update."""

    current_email: str
    new_email: str
    new_password: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export users or apply a one-time credential reset.",
    )
    parser.add_argument(
        "--export-users",
        type=Path,
        help="Write the active user list to a CSV template.",
    )
    parser.add_argument(
        "--apply",
        type=Path,
        help="Read credential updates from a CSV file and apply them.",
    )
    parser.add_argument(
        "--prompt-passwords",
        action="store_true",
        help="Prompt for each password instead of reading new_password from CSV.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print the planned updates without committing them.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip the confirmation prompt before applying changes.",
    )
    args = parser.parse_args()

    if bool(args.export_users) == bool(args.apply):
        parser.error("Specify exactly one of --export-users or --apply.")

    return args


def _normalize_email(value: str) -> str:
    return value.strip().lower()


async def export_users(path: Path) -> None:
    """Export active users to a CSV template for operator review."""

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User)
            .where(User.disabled_at.is_(None))
            .order_by(User.email.asc())
        )
        users = list(result.scalars())

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["current_email", "new_email", "new_password"],
        )
        writer.writeheader()
        for user in users:
            email = cast(str, user.email)
            writer.writerow(
                {
                    "current_email": email,
                    "new_email": email,
                    "new_password": "",
                }
            )

    print(f"Exported {len(users)} active users to {path}")
    print("Fill in new_email/new_password, then rerun with --apply.")


def load_rows(path: Path, *, prompt_passwords: bool) -> list[CredentialResetRow]:
    """Load credential updates from CSV."""

    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required_fields = {"current_email", "new_email", "new_password"}
        if not reader.fieldnames or not required_fields.issubset(reader.fieldnames):
            missing = sorted(required_fields.difference(reader.fieldnames or []))
            raise ValueError(
                f"CSV must contain current_email,new_email,new_password. Missing: {missing}"
            )

        rows: list[CredentialResetRow] = []
        for index, raw_row in enumerate(reader, start=2):
            current_email = _normalize_email(raw_row.get("current_email", ""))
            new_email = _normalize_email(raw_row.get("new_email", ""))
            csv_password = raw_row.get("new_password", "")
            new_password = csv_password

            if not current_email:
                raise ValueError(f"Row {index}: current_email is required")
            if not new_email:
                raise ValueError(f"Row {index}: new_email is required")

            if prompt_passwords:
                prompt = f"New password for {current_email} -> {new_email}: "
                confirmation_prompt = (
                    f"Confirm password for {current_email} -> {new_email}: "
                )
                new_password = getpass.getpass(prompt)
                confirmation = getpass.getpass(confirmation_prompt)
                if new_password != confirmation:
                    raise ValueError(f"Row {index}: prompted passwords do not match")

            if not new_password:
                raise ValueError(
                    f"Row {index}: new_password is required unless --prompt-passwords is used"
                )

            rows.append(
                CredentialResetRow(
                    current_email=current_email,
                    new_email=new_email,
                    new_password=new_password,
                )
            )

    if not rows:
        raise ValueError("No credential rows found in CSV")

    return rows


def validate_rows(rows: Sequence[CredentialResetRow]) -> None:
    """Perform local validation before touching the database."""

    seen_current_emails: set[str] = set()
    seen_new_emails: set[str] = set()

    for index, row in enumerate(rows, start=1):
        if row.current_email in seen_current_emails:
            raise ValueError(
                f"Row {index}: duplicate current_email {row.current_email}"
            )
        if row.new_email in seen_new_emails:
            raise ValueError(f"Row {index}: duplicate new_email {row.new_email}")

        seen_current_emails.add(row.current_email)
        seen_new_emails.add(row.new_email)

        is_valid, error = validate_password_strength(row.new_password)
        if not is_valid:
            raise ValueError(
                f"Row {index}: password for {row.current_email} is invalid: {error}"
            )


def print_plan(rows: Sequence[CredentialResetRow], *, dry_run: bool) -> None:
    """Print a redacted summary of the pending updates."""

    mode = "DRY RUN" if dry_run else "APPLY"
    print(f"{mode}: {len(rows)} active user credential updates")
    for row in rows:
        rename_note = ""
        if row.current_email != row.new_email:
            rename_note = f" -> {row.new_email}"
        print(f"  - {row.current_email}{rename_note}")


def confirm_apply(*, force: bool) -> None:
    """Require an explicit confirmation before writing changes."""

    if force:
        return

    response = input("Proceed with applying these credential updates? (yes/no): ")
    if response.strip().lower() not in {"yes", "y"}:
        raise SystemExit("Cancelled.")


async def apply_rows(rows: Sequence[CredentialResetRow], *, dry_run: bool) -> None:
    """Apply the credential reset plan."""

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User)
            .where(User.disabled_at.is_(None))
            .order_by(User.email.asc())
        )
        users = {
            _normalize_email(cast(str, user.email)): user
            for user in result.scalars()
        }

        missing_users = sorted(
            row.current_email for row in rows if row.current_email not in users
        )
        if missing_users:
            missing_text = ", ".join(missing_users)
            raise ValueError(f"Active users not found: {missing_text}")

        for row in rows:
            user = users[row.current_email]
            setattr(user, "email", row.new_email)
            setattr(user, "password_hash", get_password_hash(row.new_password))
            user.reset_login_state()
            session.add(user)

            user_id = cast(UUID, user.id)
            await revoke_all_refresh_sessions_for_user(
                session,
                user_id=user_id,
                reason="admin_password_reset",
                client_ip=None,
                user_agent="reset_user_passwords.py",
            )
            await auth_service.revoke_legacy_refresh_tokens(
                session,
                user=user,
            )

        await session.flush()

        if dry_run:
            await session.rollback()
            return

        await session.commit()


async def run() -> None:
    args = parse_args()

    if args.export_users:
        await export_users(args.export_users)
        return

    rows = load_rows(args.apply, prompt_passwords=args.prompt_passwords)
    validate_rows(rows)
    print_plan(rows, dry_run=args.dry_run)
    if not args.dry_run:
        confirm_apply(force=args.force)
    await apply_rows(rows, dry_run=args.dry_run)
    print("Done.")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
