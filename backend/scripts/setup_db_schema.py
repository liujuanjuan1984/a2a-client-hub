#!/usr/bin/env python3
"""Schema initialization script for a2a-client-hub.

This script creates or recreates the PostgreSQL schema required for the backend.
Run this before running Alembic migrations.

Usage:
  python scripts/setup_db_schema.py [--create|--recreate] [--force]
"""

from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url

# Ensure we can import the FastAPI app package when executed from anywhere.
BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.core.config import settings  # noqa: E402


def create_schema(schema_name: str | None = None) -> bool:
    """Create the configured schema if it does not exist."""

    target_schema_name = schema_name or settings.schema_name
    print(f"Creating schema '{target_schema_name}' in database...")

    try:
        engine = create_engine(settings.database_url)
        with engine.connect() as connection:
            result = connection.execute(
                text(
                    "SELECT schema_name FROM information_schema.schemata "
                    "WHERE schema_name = :schema_name"
                ),
                {"schema_name": target_schema_name},
            )
            if result.fetchone():
                print(f"Schema '{target_schema_name}' already exists.")
                return True

            connection.execute(
                text(f"CREATE SCHEMA IF NOT EXISTS {target_schema_name}")
            )
            connection.commit()
            print(f"Schema '{target_schema_name}' created successfully!")
            return True
    except Exception as exc:  # noqa: BLE001
        print(f"Error creating schema: {exc}")
        return False


def drop_schema(*, force: bool = False, schema_name: str | None = None) -> bool:
    """Drop the configured schema and all its contents."""

    target_schema_name = schema_name or settings.schema_name

    if not force:
        print(
            f"\n⚠️  WARNING: This will permanently delete schema '{target_schema_name}' "
            "and ALL its data!"
        )
        print("This action cannot be undone.")
        response = input(
            f"Are you sure you want to drop schema '{target_schema_name}'? (yes/no): "
        )
        if response.lower() not in {"yes", "y"}:
            print("Operation cancelled.")
            return False

    print(f"Dropping schema '{target_schema_name}' and all its contents...")

    try:
        engine = create_engine(settings.database_url)
        with engine.connect() as connection:
            result = connection.execute(
                text(
                    "SELECT schema_name FROM information_schema.schemata "
                    "WHERE schema_name = :schema_name"
                ),
                {"schema_name": target_schema_name},
            )
            if not result.fetchone():
                print(f"Schema '{target_schema_name}' does not exist.")
                return True

            connection.execute(
                text(f"DROP SCHEMA IF EXISTS {target_schema_name} CASCADE")
            )
            connection.commit()
            print(f"Schema '{target_schema_name}' dropped successfully!")
            return True
    except Exception as exc:  # noqa: BLE001
        print(f"Error dropping schema: {exc}")
        return False


def recreate_schema(*, force: bool = False) -> bool:
    """Drop and create the schema."""

    print(
        "Recreating schema - this will drop the existing schema and create a new one..."
    )

    if not drop_schema(force=force):
        return False
    print()
    return create_schema()


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Schema initialization script for a2a-client-hub",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/setup_db_schema.py --create
  python scripts/setup_db_schema.py --recreate
  python scripts/setup_db_schema.py --recreate --force
        """,
    )
    parser.add_argument(
        "--create",
        action="store_true",
        help="Create the schema if it does not exist",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Drop and recreate the schema (WARNING: This will delete all data!)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompts (use with caution)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_arguments()

    if not args.create and not args.recreate:
        print("Schema Management")
        print("=================")
        print("❌ Error: No operation specified.")
        print()
        print("Please specify one of the following operations:")
        print("  --create     Create schema if it does not exist")
        print("  --recreate   Drop and recreate schema (WARNING: Deletes all data!)")
        print()
        print("Optional flags:")
        print("  --force      Skip confirmation prompts (use with caution)")
        print()
        print("For more help, use: python scripts/setup_db_schema.py --help")
        sys.exit(1)

    print("Schema Management")
    print("=================")
    # Avoid printing credentials when DATABASE_URL includes a password.
    safe_url = make_url(settings.database_url).render_as_string(hide_password=True)
    print(f"Database URL: {safe_url}")
    print(f"Schema Name: {settings.schema_name}")

    if args.recreate:
        print("Mode: Recreate Schema")
        if args.force:
            print("⚠️  Force mode enabled - skipping confirmations")
    elif args.create:
        print("Mode: Create Schema")

    print()

    if args.recreate:
        success = recreate_schema(force=args.force)
        action = "recreation"
    elif args.create:
        success = create_schema()
        action = "creation"
    else:  # pragma: no cover
        print("❌ Error: No valid operation specified.")
        sys.exit(1)

    if success:
        print(f"\nSchema {action} completed successfully!")
        print("You can now run Alembic migrations:")
        print("  cd backend")
        print("  uv run alembic upgrade head")
    else:
        print(f"\nSchema {action} failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
