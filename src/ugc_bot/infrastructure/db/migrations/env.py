"""Alembic environment configuration."""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from ugc_bot.infrastructure.db import (  # noqa: F401
    dispatch_control,
    models,
    order_summary_models,
)
from ugc_bot.infrastructure.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_database_url() -> str:
    """Resolve database URL from environment or ini."""

    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url
    config_url = config.get_main_option("sqlalchemy.url")
    if not config_url:
        raise ValueError("DATABASE_URL is required for migrations.")
    return config_url


def run_migrations_offline() -> None:
    """Run migrations in offline mode."""

    url = _get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in online mode."""

    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _get_database_url()
    schema = os.getenv("MIGRATION_SCHEMA")
    kwargs: dict = {"prefix": "sqlalchemy.", "poolclass": pool.NullPool}
    if schema:
        kwargs["connect_args"] = {"options": f"-csearch_path={schema}"}
    connectable = engine_from_config(configuration, **kwargs)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            # PostgreSQL enum labels added by an earlier revision must be
            # committed before a later revision uses them in an index.
            transaction_per_migration=True,
            version_table_schema=schema,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
