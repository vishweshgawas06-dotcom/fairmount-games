"""Opt-in, read-only worker backlog snapshot. No auto-void or restart action.

Usage (from a protected operator environment):
  python -m fairmount_api.roulette.worker_status_cli
Requires FAIRMOUNT_WORKER_DATABASE_URL outside the repo and migrated DB.
Never supply credentials as CLI arguments or embed them in logs.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from typing import TextIO

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from fairmount_api.readiness import schema_ready
from fairmount_api.roulette.worker_diagnostics import inspect_due_rounds


def run(
    *,
    environment: Mapping[str, str] | None = None,
    output: TextIO | None = None,
    errors: TextIO | None = None,
) -> int:
    """Exit 0 for successful observation, 2 for configuration/DB failure.

    Due counts do not change the exit code: an operator must define an approved
    alert threshold to distinguish normal poll lag from an incident.
    """
    env = os.environ if environment is None else environment
    out = sys.stdout if output is None else output
    err = sys.stderr if errors is None else errors
    raw_url = env.get("FAIRMOUNT_WORKER_DATABASE_URL")
    try:
        if not raw_url:
            raise ValueError("Database URL absent")
        url = make_url(raw_url)
        if url.drivername != "postgresql+psycopg":
            raise ValueError("Unsupported database driver")
        engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 3})
        try:
            with engine.connect().execution_options(
                isolation_level="REPEATABLE READ"
            ) as connection:
                connection.execute(text("SET TRANSACTION READ ONLY"))
                if not schema_ready(connection):
                    raise ValueError("Schema mismatch")
                inventory = inspect_due_rounds(connection)
        finally:
            engine.dispose()
    except (SQLAlchemyError, ValueError, TypeError):
        # SQL errors and malformed URLs can embed credentials: never print them.
        print("Round diagnostics unavailable; check protected database configuration.", file=err)
        return 2
    print(
        json.dumps(
            {
                "observed_at": inventory.observed_at.isoformat(),
                "due_open": inventory.due_open,
                "due_closed": inventory.due_closed,
                "oldest_due_at": inventory.oldest_due_at.isoformat()
                if inventory.oldest_due_at
                else None,
                "latest_round_id": str(inventory.latest_round_id)
                if inventory.latest_round_id
                else None,
                "latest_state": inventory.latest_state,
                "latest_scheduled_reveal_at": inventory.latest_scheduled_reveal_at.isoformat()
                if inventory.latest_scheduled_reveal_at
                else None,
            },
            sort_keys=True,
        ),
        file=out,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
