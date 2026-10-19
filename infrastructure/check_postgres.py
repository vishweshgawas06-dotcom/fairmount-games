"""Bootstrap and verify the isolated, local-only PostgreSQL test database.

Run from the repository root after `docker compose ... up -d --wait`.
This script never drops a database or creates application tables.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
from dotenv import dotenv_values
from psycopg import sql
from psycopg.errors import DuplicateDatabase

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENV = ROOT / ".env"


def main() -> int:
    values = dotenv_values(LOCAL_ENV) if LOCAL_ENV.exists() else {}

    def setting(name: str) -> str:
        value = os.environ.get(name) or values.get(name)
        if not value:
            raise ValueError(f"Missing {name}; copy .env.example to .env for local development")
        return value

    try:
        user = setting("POSTGRES_USER")
        password = setting("POSTGRES_PASSWORD")
        dev_db = setting("POSTGRES_DB")
        test_db = setting("POSTGRES_TEST_DB")
        port = int(os.environ.get("POSTGRES_PORT") or values.get("POSTGRES_PORT") or "5432")
        if (dev_db, test_db) != ("fairmount_dev", "fairmount_test"):
            raise ValueError(
                "Only fairmount_dev and fairmount_test are allowed by this local smoke check"
            )
        if not 1 <= port <= 65535:
            raise ValueError("POSTGRES_PORT must be a valid TCP port")

        connection = dict(
            host="127.0.0.1", port=port, user=user, password=password, connect_timeout=5
        )
        # Use the development database solely to create the distinct test database if needed.
        with psycopg.connect(dbname=dev_db, autocommit=True, **connection) as admin:
            existing = admin.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (test_db,)
            ).fetchone()
            if existing is None:
                try:
                    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(test_db)))
                except DuplicateDatabase:
                    # Another local bootstrap may have created it after the lookup.
                    pass

        with psycopg.connect(dbname=test_db, **connection) as test_connection:
            row = test_connection.execute("SELECT current_database(), 1").fetchone()
            if row != (test_db, 1):
                raise RuntimeError("Connected to an unexpected database")
        print(f"PostgreSQL test database connection OK: {test_db} (localhost only)")
        return 0
    except (ValueError, psycopg.Error, RuntimeError) as exc:
        # Validation messages are safe to show; database errors may include a DSN/user.
        detail = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(
            f"PostgreSQL test database check failed: {detail}. "
            "Check .env, Docker Compose health and the localhost port.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
