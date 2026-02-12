"""
Alembic environment configuration

This file is responsible for configuring the Alembic migration environment.
Includes support for custom PostgreSQL schema management.
"""

from logging.config import fileConfig

from sqlalchemy import create_engine, pool

from alembic import context  # type: ignore[attr-defined]
from app.core.config import settings

# Import all models to ensure they are registered with SQLAlchemy
from app.db.models import *  # noqa: F401, F403
from app.db.models.base import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set the SQLAlchemy URL from our settings
config.set_main_option("sqlalchemy.url", settings.app_database_url_for_alembic)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.

naming_convention = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",  # Supports composite unique constraints.
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def include_object(object, name, type_, reflected, compare_to):
    """
    Should you include this table or schema in the migration?

    This function filters objects to only include those in our custom schema.
    """
    if type_ == "table" and object.schema != settings.schema_name:
        return False

    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    # Use database URL from environment variables via settings
    url = settings.app_database_url_for_alembic
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=settings.schema_name,
        include_schemas=True,
        compare_type=True,
        include_object=include_object,
        naming_convention=naming_convention,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    # Create engine directly from settings instead of alembic.ini
    connectable = create_engine(
        settings.app_database_url_for_alembic,
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=settings.schema_name,
            include_schemas=True,
            compare_type=True,
            include_object=include_object,
            naming_convention=naming_convention,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
