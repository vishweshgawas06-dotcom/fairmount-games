"""Verify a legacy login-role mismatch aborts migration atomically on the local test DB.

Run only at Alembic revision 20261016_02, never against the development database.
This script cleans up the deliberate mismatch and leaves the DB at revision 02; CI
then upgrades normally and runs the full suite against head.
"""

from __future__ import annotations

import os

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from infrastructure.local_db_url import local_database_url


def main() -> None:
    if os.environ.get("FAIRMOUNT_DB_NAME") != "fairmount_test":
        raise RuntimeError("Migration mismatch check requires isolated fairmount_test")

    engine = create_engine(local_database_url(test=True))
    try:
        with engine.begin() as conn:
            revision = conn.scalar(text("SELECT version_num FROM alembic_version"))
            if revision != "20261016_02":
                raise RuntimeError(f"Expected revision 20261016_02, got {revision!r}")
            account_id = conn.scalar(
                text("INSERT INTO accounts (role) VALUES ('AGENT') RETURNING id")
            )
            conn.execute(
                text("""INSERT INTO private_identities
                        (account_id, login_kind, login_identifier)
                        VALUES (:id, 'PLAYER', 'legacyplayer')"""),
                {"id": account_id},
            )

        try:
            command.upgrade(Config("alembic.ini"), "20261016_03")
        except IntegrityError:
            pass
        else:
            raise AssertionError("Mismatched legacy row unexpectedly passed the role-binding FK")

        with engine.begin() as conn:
            if conn.scalar(text("SELECT version_num FROM alembic_version")) != "20261016_02":
                raise AssertionError("Failed migration changed Alembic revision")
            if conn.scalar(
                text("SELECT login_kind FROM private_identities WHERE account_id = :id"),
                {"id": account_id},
            ) != "PLAYER":
                raise AssertionError("Failed migration modified the legacy identity")
            conn.execute(
                text("DELETE FROM private_identities WHERE account_id = :id"),
                {"id": account_id},
            )
            conn.execute(text("DELETE FROM accounts WHERE id = :id"), {"id": account_id})
        print("Legacy mismatch rejected; revision and identity unchanged; fixture removed")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
