"""Safe, read-only operator inventory output and fail-closed configuration."""

import io
import json
import unittest
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from fairmount_api.roulette.worker_diagnostics import DueRoundInventory
from fairmount_api.roulette.worker_status_cli import run
from sqlalchemy.exc import SQLAlchemyError

TEST_URL = "postgresql+psycopg://operator:private-password@db.internal/fairmount_dev"


class WorkerStatusCLITests(unittest.TestCase):
    def test_invalid_config_fails_closed_without_echoing_url(self):
        for url in (None, "sqlite:///local.db", "postgresql+psycopg://invalid:secret@["):
            with self.subTest(url=bool(url)):
                output, errors = io.StringIO(), io.StringIO()
                environment = {} if url is None else {"FAIRMOUNT_WORKER_DATABASE_URL": url}
                result = run(environment=environment, output=output, errors=errors)
                self.assertEqual(result, 2)
                self.assertEqual(output.getvalue(), "")
                self.assertNotIn("secret", errors.getvalue())
                self.assertNotIn("sqlite", errors.getvalue())

    def test_migration_mismatch_or_db_failure_does_not_print_private_details(self):
        engine = MagicMock()
        output, errors = io.StringIO(), io.StringIO()
        with patch("fairmount_api.roulette.worker_status_cli.create_engine", return_value=engine):
            with patch("fairmount_api.roulette.worker_status_cli.schema_ready", return_value=False):
                result = run(
                    environment={"FAIRMOUNT_WORKER_DATABASE_URL": TEST_URL},
                    output=output,
                    errors=errors,
                )
            self.assertEqual(result, 2)
            self.assertIn("unavailable", errors.getvalue())
            self.assertNotIn("private-password", errors.getvalue())
            engine.connect.side_effect = SQLAlchemyError("operator:private-password@db.internal")
            errors = io.StringIO()
            self.assertEqual(
                run(
                    environment={"FAIRMOUNT_WORKER_DATABASE_URL": TEST_URL},
                    output=output,
                    errors=errors,
                ),
                2,
            )
            self.assertNotIn("private-password", errors.getvalue())
            self.assertEqual(output.getvalue(), "")
        self.assertEqual(engine.dispose.call_count, 2)

    def test_success_emits_only_aggregate_fields_not_outcomes_or_accounts(self):
        engine = MagicMock()
        instant = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
        inventory = DueRoundInventory(instant, 2, 1, instant, uuid.uuid4(), "CLOSED", instant)
        output, errors = io.StringIO(), io.StringIO()
        with patch("fairmount_api.roulette.worker_status_cli.create_engine", return_value=engine):
            with patch("fairmount_api.roulette.worker_status_cli.schema_ready", return_value=True):
                with patch(
                    "fairmount_api.roulette.worker_status_cli.inspect_due_rounds",
                    return_value=inventory,
                ):
                    result = run(
                        environment={"FAIRMOUNT_WORKER_DATABASE_URL": TEST_URL},
                        output=output,
                        errors=errors,
                    )
        self.assertEqual(result, 0)  # counts have no unapproved alert threshold
        self.assertEqual(errors.getvalue(), "")
        payload = json.loads(output.getvalue())
        self.assertEqual((payload["due_open"], payload["due_closed"]), (2, 1))
        self.assertEqual(payload["latest_state"], "CLOSED")
        self.assertEqual(
            set(payload),
            {
                "observed_at",
                "due_open",
                "due_closed",
                "oldest_due_at",
                "latest_round_id",
                "latest_state",
                "latest_scheduled_reveal_at",
            },
        )
        for private in ("private-password", "account", "player", "stake", "winning_number"):
            self.assertNotIn(private, output.getvalue())


if __name__ == "__main__":
    unittest.main()
