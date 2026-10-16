"""Local PostgreSQL Alembic runner for P02-T02a."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from fairmount_api.db.models import Base
from sqlalchemy import create_engine, pool

from infrastructure.local_db_url import local_database_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def database_url():
    selected = os.environ.get("FAIRMOUNT_DB_NAME", "fairmount_dev")
    if selected not in {"fairmount_dev", "fairmount_test"}:
        raise ValueError("FAIRMOUNT_DB_NAME must be fairmount_dev or fairmount_test")
    return local_database_url(test=selected == "fairmount_test")


def run_migrations_offline() -> None:
    context.configure(
        url=database_url().render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection, target_metadata=target_metadata, compare_type=True
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
