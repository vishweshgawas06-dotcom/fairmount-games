"""Alembic environment: URL from the environment, metadata from the ORM models."""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine, pool

from fairmount_api.db import models  # noqa: F401  (registers tables on the metadata)
from fairmount_api.db.base import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    url = (
        config.get_main_option("sqlalchemy.url")
        or os.environ.get("FAIRMOUNT_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
    )
    if not url:
        raise RuntimeError("Set FAIRMOUNT_DATABASE_URL (or DATABASE_URL) to run migrations.")
    return url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
