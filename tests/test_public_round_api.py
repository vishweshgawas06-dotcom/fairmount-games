"""HTTP boundary never reveals private bets or an unrevealed winner."""

import os
import unittest
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from fairmount_api.main import app
from fairmount_api.readiness import _configured_engine
from fairmount_api.roulette.public_snapshot import RevealedRound, RoundSnapshot
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from infrastructure.local_db_url import local_database_url

URL = "/api/v1/roulette/round"


class PublicRoundAPITests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_read_only_preview_assets_and_root_redirect(self):
        root = self.client.get("/", follow_redirects=False)
        self.assertEqual((root.status_code, root.headers["location"]), (307, "/preview/"))
        page = self.client.get("/preview/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Viewing mode only", page.text)
        self.assertIn("No wagers are accepted", page.text)
        for path in ("styles.css", "app.js", "wheel.mjs"):
            self.assertEqual(self.client.get("/preview/" + path).status_code, 200)
        self.assertEqual(self.client.get("/preview/wheel.test.mjs").status_code, 404)

    def test_no_database_fails_closed_without_credentials(self):
        with patch("fairmount_api.roulette.public_api._configured_engine", return_value=None):
            response = self.client.get(URL)
        self.assertEqual((response.status_code, response.json()), (503, {"status": "unavailable"}))
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_wrong_schema_and_database_failure_are_generic(self):
        engine = MagicMock()
        with patch("fairmount_api.roulette.public_api._configured_engine", return_value=engine):
            with patch("fairmount_api.roulette.public_api.schema_ready", return_value=False):
                response = self.client.get(URL)
                self.assertEqual(
                    (response.status_code, response.json()), (503, {"status": "unavailable"})
                )
            engine.connect.side_effect = SQLAlchemyError("private-host:secret")
            response = self.client.get(URL)
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("private-host", response.text)
            self.assertNotIn("secret", response.text)

    def test_public_payload_has_only_reveal_safe_fields(self):
        engine = MagicMock()
        round_id = uuid.uuid4()
        earlier = uuid.uuid4()
        now = datetime(2026, 10, 24, 10, 0, tzinfo=UTC)
        snapshot = RoundSnapshot(
            now,
            round_id,
            "SPINNING",
            now,
            now,
            None,
            (RevealedRound(earlier, "SETTLED", 17),),
        )
        with patch("fairmount_api.roulette.public_api._configured_engine", return_value=engine):
            with patch("fairmount_api.roulette.public_api.schema_ready", return_value=True):
                with patch(
                    "fairmount_api.roulette.public_api.read_public_round_snapshot",
                    return_value=snapshot,
                ):
                    response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        payload = response.json()
        self.assertEqual(payload["round"]["phase"], "SPINNING")
        self.assertIsNone(payload["round"]["winning_number"])
        self.assertEqual(
            payload["recent"],
            [{"round_id": str(earlier), "state": "SETTLED", "winning_number": 17}],
        )
        self.assertEqual(set(payload), {"observed_at", "round", "recent"})
        for private in ("bet", "stake", "account", "wallet", "balance", "player", "token"):
            self.assertNotIn(private, response.text.lower())

    @unittest.skipUnless(
        os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
    )
    def test_public_http_reads_migrated_postgresql_without_private_fields(self):
        url = local_database_url(test=True).render_as_string(hide_password=False)
        with patch.dict(os.environ, {"FAIRMOUNT_API_DATABASE_URL": url}):
            _configured_engine.cache_clear()
            try:
                response = self.client.get(URL)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(set(response.json()), {"observed_at", "round", "recent"})
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                for private in ("bet", "stake", "account", "wallet", "balance", "player"):
                    self.assertNotIn(private, response.text.lower())
            finally:
                engine = _configured_engine()
                if engine is not None:
                    engine.dispose()
                _configured_engine.cache_clear()


if __name__ == "__main__":
    unittest.main()
