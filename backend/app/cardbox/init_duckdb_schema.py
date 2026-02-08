"""DuckDB schema initialization utilities for Cardbox.

This module provides utilities to initialize and manage DuckDB schema for the
Cardbox context engine. It supports both automatic detection and manual
initialization of database tables.

Usage:
    # As a module
    from app.cardbox.init_duckdb_schema import initialize_schema, ensure_schema_exists

    # Initialize for a specific user (automatically handles user- prefix)
    initialize_schema("123")  # Will create tenant "user-123"

    # Check if schema exists
    if not ensure_schema_exists("123"):
        initialize_schema("123")

    # As a command line script
    python -m app.cardbox.init_duckdb_schema --user 123
    python -m app.cardbox.init_duckdb_schema --all-users
"""

import argparse
import logging
import sys
import traceback
from pathlib import Path
from typing import Any, List, Union

from app.api.deps import get_db
from app.cardbox.config import setup_cardbox
from app.cardbox.service import cardbox_service
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.user import User

logger = get_logger(__name__)


def ensure_storage_directory() -> Path:
    """Ensure the storage directory exists and return its path.

    Returns
    -------
    Path
        The storage directory path.

    Raises
    ------
    OSError
        If the directory cannot be created.
    """
    storage_path = Path(settings.card_box_duckdb_path)
    storage_dir = storage_path.parent

    try:
        storage_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Storage directory ensured: {storage_dir}")
        return storage_dir
    except OSError as e:
        logger.error(f"Failed to create storage directory {storage_dir}: {e}")
        raise


def setup_cardbox_configuration() -> None:
    """Setup Cardbox configuration with current settings.

    This function is idempotent and can be called multiple times safely.
    """
    try:
        setup_cardbox(settings)
        logger.info("Cardbox configuration applied successfully")
    except Exception as e:
        logger.error(f"Failed to setup Cardbox configuration: {e}")
        raise


def initialize_schema(
    user_id: Union[str, int], cleanup_test_boxes: bool = True
) -> bool:
    """Initialize DuckDB schema for a specific user.

    This function creates the necessary database tables by triggering
    the Cardbox initialization process. It uses the same mechanism as
    the application runtime to ensure consistency.

    Parameters
    ----------
    user_id : Union[str, int]
        The user identifier. Will be automatically converted to tenant_id
        using tenant_for_user() function.
    cleanup_test_boxes : bool, default True
        Whether to clean up test CardBoxes after initialization.

    Returns
    -------
    bool
        True if initialization was successful, False otherwise.

    Examples
    --------
    >>> initialize_schema("123")
    True

    >>> initialize_schema(456)
    True
    """
    try:
        logger.info(f"Initializing schema for user: {user_id}")

        # Ensure storage directory exists
        ensure_storage_directory()

        # Setup configuration
        setup_cardbox_configuration()

        # Use CardBoxService to initialize storage
        success = cardbox_service.initialize_storage(user_id, cleanup_test_boxes)

        if success:
            logger.info(f"Schema initialization successful for user: {user_id}")
            print(f"Schema initialization successful for user: {user_id}")
        else:
            logger.error(f"Schema initialization failed for user: {user_id}")
            print(f"Schema initialization failed for user: {user_id}")
        return success

    except Exception as e:
        logger.error(f"Schema initialization failed for user '{user_id}': {e}")
        return False


def ensure_schema_exists(user_id: Union[str, int]) -> bool:
    """Check if DuckDB schema exists for a specific user.

    This function performs a lightweight check without creating any test data.

    Parameters
    ----------
    user_id : Union[str, int]
        The user identifier. Will be automatically converted to tenant_id
        using tenant_for_user() function.

    Returns
    -------
    bool
        True if schema exists and is accessible, False otherwise.
    """
    try:
        logger.debug(f"Checking schema existence for user: {user_id}")

        # Ensure storage directory exists
        ensure_storage_directory()

        # Setup configuration
        setup_cardbox_configuration()

        # Use CardBoxService to check storage
        exists = cardbox_service.check_storage_exists(user_id)

        logger.debug(f"Schema exists for user {user_id}: {exists}")
        return exists

    except Exception as e:
        logger.debug(f"Schema check failed for user '{user_id}': {e}")
        return False


def initialize_schema_for_multiple_users(user_ids: List[Union[str, int]]) -> dict:
    """Initialize schema for multiple users.

    Parameters
    ----------
    user_ids : List[Union[str, int]]
        List of user identifiers.

    Returns
    -------
    dict
        Dictionary mapping user_id to success status.
    """
    results = {}

    logger.info(f"Initializing schema for {len(user_ids)} users")

    for user_id in user_ids:
        results[user_id] = initialize_schema(user_id)

    successful = sum(1 for success in results.values() if success)
    logger.info(
        f"Schema initialization completed: {successful}/{len(user_ids)} successful"
    )

    return results


def initialize_schema_for_all_existing_users() -> dict:
    """Initialize schema for all existing users in the system.

    This function queries the main PostgreSQL database to find all users and
    initializes Cardbox schema for each of them.

    Returns
    -------
    dict
        Dictionary mapping user_id to success status.
    """
    db = None
    try:
        logger.info("Initializing schema for all existing users")

        # Get database session
        db = next(get_db())

        # Get all users from the database, filtering out None/empty user IDs
        users = db.query(User).filter(User.id.isnot(None)).all()

        if not users:
            logger.warning("No users found in the database")
            return {}

        # Extract user IDs
        user_ids = [user.id for user in users if user.id is not None]

        logger.info(f"Found {len(user_ids)} users to initialize")

        return initialize_schema_for_multiple_users(user_ids)

    except Exception as e:
        logger.error(f"Failed to initialize schema for all users: {e}")
        return {}
    finally:
        if db:
            try:
                db.close()
            except Exception as e:
                logger.warning(f"Failed to close database session: {e}")


def main() -> Any:
    """Command line interface for schema initialization."""
    parser = argparse.ArgumentParser(
        description="Initialize DuckDB schema for Cardbox",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Initialize schema for a specific user (user ID will be converted to tenant automatically)
  python -m app.cardbox.init_duckdb_schema --user 123

  # Initialize schema for all existing users
  python -m app.cardbox.init_duckdb_schema --all-users

  # Check if schema exists for a user
  python -m app.cardbox.init_duckdb_schema --check 123

  # Initialize schema for multiple users
  python -m app.cardbox.init_duckdb_schema --users 123 456 789

  # Initialize schema with custom database path
  python -m app.cardbox.init_duckdb_schema --user 123 --db-path /custom/path/cardbox.duckdb
        """,
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--user", help="Initialize schema for a specific user (user ID)")
    group.add_argument(
        "--users", nargs="+", help="Initialize schema for multiple users (user IDs)"
    )
    group.add_argument(
        "--all-users",
        action="store_true",
        help="Initialize schema for all existing users",
    )
    group.add_argument(
        "--check", help="Check if schema exists for a specific user (user ID)"
    )

    parser.add_argument(
        "--db-path",
        help="Override the DuckDB database path (temporarily overrides CARD_BOX_DUCKDB_PATH)",
    )

    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Don't clean up test CardBoxes after initialization",
    )

    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    # Configure logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Override database path if provided
    if args.db_path:
        original_path = settings.card_box_duckdb_path
        settings.card_box_duckdb_path = args.db_path
        logger.info(
            f"Using custom database path override: {args.db_path} (was: {original_path})"
        )

        # Re-setup Cardbox configuration with new path
        setup_cardbox_configuration()
        # Diagnostic: confirm the effective path after configuration
        logger.info(
            f"Effective DuckDB path after configure: {settings.card_box_duckdb_path}"
        )

    try:
        if args.user:
            user_id = args.user
            success = initialize_schema(user_id, cleanup_test_boxes=not args.no_cleanup)
            if success:
                print(f"✓ Schema initialized successfully for user: {user_id}")
                sys.exit(0)
            else:
                print(f"✗ Failed to initialize schema for user: {user_id}")
                sys.exit(1)

        elif args.users:
            user_ids = args.users
            results = initialize_schema_for_multiple_users(user_ids)
            successful = [uid for uid, success in results.items() if success]
            failed = [uid for uid, success in results.items() if not success]

            if successful:
                print(f"✓ Successfully initialized schema for: {', '.join(successful)}")
            if failed:
                print(f"✗ Failed to initialize schema for: {', '.join(failed)}")

            sys.exit(0 if not failed else 1)

        elif args.all_users:
            results = initialize_schema_for_all_existing_users()
            if results:
                successful = [uid for uid, success in results.items() if success]
                failed = [uid for uid, success in results.items() if not success]

                print(f"✓ Successfully initialized schema for {len(successful)} users")
                if failed:
                    print(f"✗ Failed to initialize schema for {len(failed)} users")

                sys.exit(0 if not failed else 1)
            else:
                print("No users found to initialize schema for")
                sys.exit(0)

        elif args.check:
            user_id = args.check
            exists = ensure_schema_exists(user_id)
            if exists:
                print(f"✓ Schema exists for user: {user_id}")
                sys.exit(0)
            else:
                print(f"✗ Schema does not exist for user: {user_id}")
                sys.exit(1)

    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        if args.verbose:
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    # ensure_storage_directory()
    setup_cardbox_configuration()
    # initialize_schema_for_all_existing_users()
    initialize_schema("0cb769da-bbbd-4268-abf2-b2a5f7f3aed0")
