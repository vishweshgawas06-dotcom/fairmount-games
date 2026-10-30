"""Guards for the local test-database reset helper; no database is touched here."""

import contextlib
import io
import unittest

from infrastructure.reset_test_db import main, reset_test_database


class ResetTestDatabaseGuardTests(unittest.TestCase):
    def test_reset_requires_explicit_confirmation(self):
        with self.assertRaises(ValueError):
            reset_test_database(confirmed=False)

    def test_only_the_disposable_test_database_is_allowed(self):
        from infrastructure.reset_test_db import _validated

        self.assertEqual(_validated("fairmount_test"), "fairmount_test")
        for name in ("fairmount_dev", "postgres", "template1", "", None):
            with self.subTest(name=name), self.assertRaises(ValueError):
                _validated(name)

    def test_cli_refuses_without_the_flag(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(main([]), 2)
        self.assertIn("--yes", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
