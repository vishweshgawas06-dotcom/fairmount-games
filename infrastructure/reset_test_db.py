"""Recreate the disposable local PostgreSQL **test** database between suite runs.

The PostgreSQL integration tests commit real bootstrap, audit, wallet and
roulette rows, and migrations deliberately block TRUNCATE/DELETE on immutable
audit and ledger tables. CI therefore starts from a fresh volume each run;
locally this script drops and recreates only `fairmount_test` so the suite can
run again. The migrated schema is recreated by `alembic upgrade head`
afterwards.

It never targets `fairmount_dev`, never touches another database, and refuses to
run without an explicit `--yes`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg
from psycopg import sql

from infrastructure.local_db_url import local_database_url

ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE = "fairmount_test"
_MAINTENANCE_DATABASES = ("postgres", "template1")


def _validated(database: str | None) -> str:
    """Only the isolated test database may be recreated by this local helper."""
    if database != TEST_DATABASE:
        raise ValueError(f"Refusing to reset anything but {TEST_DATABASE}")
    return database


def reset_test_database(*, confirmed: bool) -> None:
    """Drop and recreate `fairmount_test` using the local .env credentials."""
    if confirmed is not True:
        raise ValueError("Refusing to reset without --yes")
    url = local_database_url(test=True)
    database = _validated(url.database)
    settings = {
        "host": "127.0.0.1",
        "port": url.port,
        "user": url.username,
        "password": url.password,
        "connect_timeout": 5,
    }
    last_error: Exception | None = None
    for maintenance in _MAINTENANCE_DATABASES:
        try:
            with psycopg.connect(dbname=maintenance, autocommit=True, **settings) as admin:
                admin.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    (database,),
                )
                admin.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database))
                )
                admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
            return
        except psycopg.OperationalError as exc:  # maintenance database unavailable
            last_error = exc
    raise RuntimeError(f"No local maintenance database reachable: {type(last_error).__name__}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--yes",
        action="store_true",
        help=f"required confirmation; only {TEST_DATABASE} is ever recreated",
    )
    arguments = parser.parse_args(argv)
    if not arguments.yes:
        print(
            f"Refusing to reset {TEST_DATABASE} without --yes. "
            "This recreates only the disposable local test database.",
            file=sys.stderr,
        )
        return 2
    try:
        reset_test_database(confirmed=True)
    except (ValueError, RuntimeError) as exc:
        print(f"Test database reset failed: {exc}", file=sys.stderr)
        return 1
    print(f"Recreated empty {TEST_DATABASE}; run alembic upgrade head before the suite.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
