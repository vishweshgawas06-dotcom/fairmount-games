"""Local CLI guard and post-commit delivery tests; no real secrets/DB are used."""

import io
import os
import unittest
import uuid
from unittest.mock import patch

from fairmount_api.identity.owner_bootstrap import PendingOwnerSecret
from fairmount_api.identity.owner_setup_cli import main


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


class FakeEngine:
    def __init__(self, events: list[str]):
        self.events = events

    def begin(self):
        engine = self

        class Transaction:
            def __enter__(self):
                engine.events.append("begin")
                return object()

            def __exit__(self, exc_type, exc_value, traceback):
                engine.events.append("commit" if exc_type is None else "rollback")

        return Transaction()

    def dispose(self):
        self.events.append("dispose")


class CheckedOutput(Terminal):
    def __init__(self, events: list[str], *, fail=False):
        super().__init__()
        self.events = events
        self.fail = fail

    def write(self, value: str) -> int:
        self.events.append("output")
        if "test-secret" in value:
            if "commit" not in self.events:
                raise AssertionError("Secret written before commit")
            if self.fail:
                raise OSError("Simulated terminal failure")
        return super().write(value)


class OwnerSetupCLITests(unittest.TestCase):
    def test_refuses_redirected_terminal_and_unselected_database(self) -> None:
        with patch("fairmount_api.identity.owner_setup_cli.create_engine") as create:
            self.assertEqual(
                main(["init"], input_stream=io.StringIO(),
                     output_stream=io.StringIO(), error_stream=io.StringIO()),
                2,
            )
            create.assert_not_called()
        with patch.dict(os.environ, {}, clear=True):
            with patch("fairmount_api.identity.owner_setup_cli.create_engine") as create:
                self.assertEqual(
                    main(["init"], input_stream=Terminal(),
                         output_stream=Terminal(), error_stream=Terminal()),
                    2,
                )
                create.assert_not_called()

    def test_initial_secret_only_written_after_commit(self) -> None:
        events: list[str] = []
        engine = FakeEngine(events)
        output = CheckedOutput(events)
        result = PendingOwnerSecret(account_id=uuid.uuid4(), secret="test-secret")
        with (
            patch.dict(os.environ, {"FAIRMOUNT_DB_NAME": "fairmount_dev"}),
            patch("fairmount_api.identity.owner_setup_cli.local_database_url"),
            patch("fairmount_api.identity.owner_setup_cli.create_engine", return_value=engine),
            patch("fairmount_api.identity.owner_setup_cli.bootstrap_owner", return_value=result),
        ):
            self.assertEqual(
                main(["init"], input_stream=Terminal(), output_stream=output,
                     error_stream=Terminal()),
                0,
            )
        self.assertIn("test-secret", output.getvalue())
        self.assertEqual(events[0:2], ["begin", "commit"])
        self.assertEqual(events[-1], "dispose")

    def test_commit_or_delivery_failure_never_reports_secret_in_errors(self) -> None:
        for fail_delivery in (False, True):
            with self.subTest(fail_delivery=fail_delivery):
                events: list[str] = []
                output = CheckedOutput(events, fail=fail_delivery)
                errors = Terminal()
                result = PendingOwnerSecret(account_id=uuid.uuid4(), secret="test-secret")
                operation = (
                    result if fail_delivery else ValueError("Simulated DB failure")
                )
                with (
                    patch.dict(os.environ, {"FAIRMOUNT_DB_NAME": "fairmount_dev"}),
                    patch("fairmount_api.identity.owner_setup_cli.local_database_url"),
                    patch("fairmount_api.identity.owner_setup_cli.create_engine",
                          return_value=FakeEngine(events)),
                    patch("fairmount_api.identity.owner_setup_cli.bootstrap_owner") as boot,
                ):
                    boot.side_effect = None if fail_delivery else operation
                    boot.return_value = result
                    self.assertEqual(
                        main(["init"], input_stream=Terminal(), output_stream=output,
                             error_stream=errors),
                        1,
                    )
                self.assertNotIn("test-secret", errors.getvalue())
                self.assertEqual("commit" in events, fail_delivery)


if __name__ == "__main__":
    unittest.main()
