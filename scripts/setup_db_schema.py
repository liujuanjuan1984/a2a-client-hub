#!/usr/bin/env python3
"""
Schema initialization script for Common Compass

This script creates or recreates the custom PostgreSQL schema required for the application.
Run this before running Alembic migrations.

Usage:
    python scripts/setup_db_schema.py [--recreate] [--force]

Options:
    --recreate  Drop and recreate the schema (WARNING: This will delete all data!)
    --force     Skip confirmation prompts (use with caution)
"""

import argparse
import os
import sys

# Add the parent directory to the path so we can import our app
sys.path.append(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from sqlalchemy import create_engine, text

from app.core.config import settings


def create_schema(schema_name=None):
    """
    Create the custom schema in PostgreSQL database

    Args:
        schema_name (str, optional): Schema name to create. If None, uses settings.schema_name
    """
    target_schema_name = schema_name or settings.schema_name
    print(f"Creating schema '{target_schema_name}' in database...")

    try:
        # Create engine
        engine = create_engine(settings.database_url)

        # Create schema
        with engine.connect() as connection:
            # Check if schema already exists
            result = connection.execute(text(
                "SELECT schema_name FROM information_schema.schemata WHERE schema_name = :schema_name"
            ), {"schema_name": target_schema_name})

            if result.fetchone():
                print(f"Schema '{target_schema_name}' already exists.")
                return True

            # Create the schema
            connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {target_schema_name}"))
            connection.commit()

            print(f"Schema '{target_schema_name}' created successfully!")
            return True

    except Exception as e:
        print(f"Error creating schema: {e}")
        return False


def drop_schema(force=False, schema_name=None):
    """
    Drop the custom schema and all its contents from PostgreSQL database

    Args:
        force (bool): If True, skip confirmation prompt
        schema_name (str, optional): Schema name to drop. If None, uses settings.schema_name

    Returns:
        bool: True if successful, False otherwise
    """
    target_schema_name = schema_name or settings.schema_name

    if not force:
        print(f"\n⚠️  WARNING: This will permanently delete schema '{target_schema_name}' and ALL its data!")
        print("This action cannot be undone.")
        response = input(f"Are you sure you want to drop schema '{target_schema_name}'? (yes/no): ")
        if response.lower() not in ['yes', 'y']:
            print("Operation cancelled.")
            return False

    print(f"Dropping schema '{target_schema_name}' and all its contents...")

    try:
        # Create engine
        engine = create_engine(settings.database_url)

        # Drop schema
        with engine.connect() as connection:
            # Check if schema exists
            result = connection.execute(text(
                "SELECT schema_name FROM information_schema.schemata WHERE schema_name = :schema_name"
            ), {"schema_name": target_schema_name})

            if not result.fetchone():
                print(f"Schema '{target_schema_name}' does not exist.")
                return True

            # Drop the schema and all its contents
            connection.execute(text(f"DROP SCHEMA IF EXISTS {target_schema_name} CASCADE"))
            connection.commit()

            print(f"Schema '{target_schema_name}' dropped successfully!")
            return True

    except Exception as e:
        print(f"Error dropping schema: {e}")
        return False


def recreate_schema(force=False):
    """
    Recreate the custom schema (drop and create)

    Args:
        force (bool): If True, skip confirmation prompts

    Returns:
        bool: True if successful, False otherwise
    """
    print("Recreating schema - this will drop the existing schema and create a new one...")

    # Drop existing schema
    if not drop_schema(force):
        return False

    print()  # Add blank line for readability

    # Create new schema
    return create_schema()


def parse_arguments():
    """
    Parse command line arguments

    Returns:
        argparse.Namespace: Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description="Schema initialization script for Common Compass",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/setup_db_schema.py --create           # Create schema if not exists
  python scripts/setup_db_schema.py --recreate         # Drop and recreate schema
  python scripts/setup_db_schema.py --recreate --force # Recreate without confirmation
        """
    )

    parser.add_argument(
        '--create',
        action='store_true',
        help='Create the schema if it does not exist'
    )

    parser.add_argument(
        '--recreate',
        action='store_true',
        help='Drop and recreate the schema (WARNING: This will delete all data!)'
    )

    parser.add_argument(
        '--force',
        action='store_true',
        help='Skip confirmation prompts (use with caution)'
    )

    return parser.parse_args()


def main():
    """
    Main function to create or recreate schema based on command line arguments
    """
    args = parse_arguments()

    # Check if no arguments were provided
    if not args.create and not args.recreate:
        print("Common Compass - Schema Management")
        print("==================================")
        print("❌ Error: No operation specified.")
        print()
        print("Please specify one of the following operations:")
        print("  --create     Create schema if it does not exist")
        print("  --recreate   Drop and recreate schema (WARNING: Deletes all data!)")
        print()
        print("Optional flags:")
        print("  --force      Skip confirmation prompts (use with caution)")
        print()
        print("Examples:")
        print("  python scripts/setup_db_schema.py --create           # Safe: Create if not exists")
        print("  python scripts/setup_db_schema.py --recreate         # Dangerous: Drop and recreate")
        print("  python scripts/setup_db_schema.py --recreate --force # Very dangerous: No confirmation")
        print()
        print("For more help, use: python scripts/setup_db_schema.py --help")
        sys.exit(1)

    print("Common Compass - Schema Management")
    print("==================================")
    print(f"Database URL: {settings.database_url}")
    print(f"Schema Name: {settings.schema_name}")

    if args.recreate:
        print("Mode: Recreate Schema")
        if args.force:
            print("⚠️  Force mode enabled - skipping confirmations")
    elif args.create:
        print("Mode: Create Schema")

    print()

    # Execute the appropriate action
    if args.recreate:
        success = recreate_schema(args.force)
        action = "recreation"
    elif args.create:
        success = create_schema()
        action = "creation"
    else:
        # This should not happen due to the check above, but just in case
        print("❌ Error: No valid operation specified.")
        sys.exit(1)

    # Print results
    if success:
        print(f"\nSchema {action} completed successfully!")
        print("You can now run Alembic migrations:")
        print("  cd backend")
        print("  alembic upgrade head")
    else:
        print(f"\nSchema {action} failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
