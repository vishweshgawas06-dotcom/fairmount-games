"""Smoke tests for the initial API foundation."""

import os
import unittest
from unittest.mock import MagicMock, patch

from fairmount_api.main import app
from fairmount_api.readiness import EXPECTED_REVISION, _configured_engine, database_ready
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from infrastructure.local_db_url import local_database_url


class ApiHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_liveness_returns_service_status(self) -> None:
        response = self.client.get("/health/live")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"status": "ok", "service": "fairmount-api"},
        )

    def test_gameplay_routes_are_not_claimed_as_implemented(self) -> None:
        response = self.client.get("/health/live")

        self.assertNotIn("database", response.json())
        self.assertNotIn("round", response.json())

    def test_readiness_fails_closed_without_configuration_or_with_unsafe_scheme(self) -> None:
        with patch.dict(os.environ, {"FAIRMOUNT_API_DATABASE_URL": ""}):
            _configured_engine.cache_clear()
            response = self.client.get("/health/ready")
            self.assertEqual(
                (response.status_code, response.json()), (503, {"status": "unavailable"})
            )
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(self.client.get("/health/live").status_code, 200)
        with patch.dict(os.environ, {"FAIRMOUNT_API_DATABASE_URL": "sqlite:///local.db"}):
            _configured_engine.cache_clear()
            response = self.client.get("/health/ready")
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("sqlite", response.text)
        _configured_engine.cache_clear()

    def test_readiness_has_no_public_database_error_details(self) -> None:
        with patch.dict(
            os.environ,
            {
                "FAIRMOUNT_API_DATABASE_URL": "postgresql+psycopg://bad-secret@invalid-host.invalid:5432/example"
            },
        ):
            _configured_engine.cache_clear()
            try:
                response = self.client.get("/health/ready")
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json(), {"status": "unavailable"})
                self.assertNotIn("bad-secret", response.text)
            finally:
                engine = _configured_engine()
                if engine is not None:
                    engine.dispose()
                _configured_engine.cache_clear()

    def test_readiness_rejects_wrong_revision_and_database_errors(self) -> None:
        engine = MagicMock()
        connection = engine.connect.return_value.__enter__.return_value
        with patch("fairmount_api.readiness._configured_engine", return_value=engine):
            connection.scalar.return_value = "older-revision"
            self.assertFalse(database_ready())
            connection.scalar.return_value = EXPECTED_REVISION
            self.assertTrue(database_ready())
            connection.scalar.side_effect = SQLAlchemyError("private connection details")
            self.assertFalse(database_ready())

    @unittest.skipUnless(
        os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
    )
    def test_readiness_checks_actual_migration_revision(self) -> None:
        # CI has run Alembic upgrade head in the isolated fairmount_test DB.
        database_url = local_database_url(test=True).render_as_string(hide_password=False)
        with patch.dict(os.environ, {"FAIRMOUNT_API_DATABASE_URL": database_url}):
            _configured_engine.cache_clear()
            try:
                response = self.client.get("/health/ready")
                self.assertEqual(
                    (response.status_code, response.json()), (200, {"status": "ready"})
                )
                self.assertEqual(response.headers["Cache-Control"], "no-store")
            finally:
                engine = _configured_engine()
                if engine is not None:
                    engine.dispose()
                _configured_engine.cache_clear()


if __name__ == "__main__":
    unittest.main()
