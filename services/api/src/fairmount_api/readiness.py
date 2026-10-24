"""Fail-closed API database/schema readiness, separate from process liveness.

A successful response only means this process can read the expected migration
revision. It does NOT attest to reserve solvency, round-worker supervision,
backups, authorized routes, or an integrated game. No database URL is logged.
"""

from __future__ import annotations

import os
from functools import lru_cache

from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

EXPECTED_REVISION = "20261023_03"


@lru_cache(maxsize=1)
def _configured_engine() -> Engine | None:
    """Configure a bounded pool once per API process; restart to rotate URLs."""
    raw_url = os.environ.get("FAIRMOUNT_API_DATABASE_URL")
    if not raw_url:
        return None
    try:
        url = make_url(raw_url)
        if url.drivername != "postgresql+psycopg":
            return None
        return create_engine(
            url,
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=0,
            pool_timeout=2,
            connect_args={"connect_timeout": 2},
        )
    except (SQLAlchemyError, ValueError, TypeError):
        # Deliberately return no exception text: an invalid URL can contain a
        # password, host or database name. Config faults are not public data.
        return None


def schema_ready(connection: Connection) -> bool:
    """Read the exact expected migration revision on this same connection."""
    return connection.scalar(text("SELECT version_num FROM alembic_version")) == EXPECTED_REVISION


def database_ready() -> bool:
    """True iff the explicit PostgreSQL URL reaches the exact expected schema."""
    engine = _configured_engine()
    if engine is None:
        return False
    try:
        with engine.connect() as connection:
            return schema_ready(connection)
    except SQLAlchemyError:
        return False
