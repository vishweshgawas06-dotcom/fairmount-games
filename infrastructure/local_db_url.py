"""Local-only connection settings for account-schema migrations and tests.

Not a production configuration module. It never accepts a remote host or an arbitrary
schema name, and it does not print credentials.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[1]


def local_database_url(*, test: bool = False) -> URL:
    values = dotenv_values(ROOT / ".env") if (ROOT / ".env").exists() else {}

    def setting(name: str) -> str:
        value = os.environ.get(name) or values.get(name)
        if not value:
            raise ValueError(f"Missing {name}; copy .env.example to .env for local development")
        return value

    dev_db = setting("POSTGRES_DB")
    test_db = setting("POSTGRES_TEST_DB")
    if (dev_db, test_db) != ("fairmount_dev", "fairmount_test"):
        raise ValueError("Only the local fairmount_dev/fairmount_test databases are allowed")
    port = int(os.environ.get("POSTGRES_PORT") or values.get("POSTGRES_PORT") or "5432")
    if not 1 <= port <= 65535:
        raise ValueError("POSTGRES_PORT must be a valid TCP port")
    return URL.create(
        "postgresql+psycopg",
        username=setting("POSTGRES_USER"),
        password=setting("POSTGRES_PASSWORD"),
        host="127.0.0.1",
        port=port,
        database=test_db if test else dev_db,
    )
