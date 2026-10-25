"""Opt-in direct-TLS private self-wallet HTTP boundary; no client account IDs."""

import secrets
import unittest
import uuid
from unittest.mock import MagicMock, patch

from fairmount_api.identity.http_boundary import SESSION_COOKIE
from fairmount_api.main import app
from fairmount_api.resource_reads import ResourceUnavailable, WalletView
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

URL = "/api/v1/me/wallet"
CONFIG = {
    "FAIRMOUNT_AUTH_EDGE_MODE": "direct-tls",
    "FAIRMOUNT_PUBLIC_ORIGIN": "https://game.example",
}


class PrivateReadAPITests(unittest.TestCase):
    def setUp(self):
        self.token = secrets.token_urlsafe(32)
        self.client = TestClient(
            app, base_url="https://game.example", client=("203.0.113.21", 54000)
        )
        self.cookie = {"Cookie": f"{SESSION_COOKIE}={self.token}"}

    def test_disabled_by_default_plain_http_and_no_cookie(self):
        with patch.dict("os.environ", {"FAIRMOUNT_AUTH_EDGE_MODE": ""}):
            self.assertEqual(self.client.get(URL, headers=self.cookie).status_code, 503)
        with patch.dict("os.environ", CONFIG):
            plain = TestClient(app, base_url="http://game.example", client=("203.0.113.21", 54000))
            self.assertEqual(plain.get(URL, headers=self.cookie).status_code, 503)
            self.assertEqual(self.client.get(URL).status_code, 401)

    def test_other_origin_site_forwarding_and_client_id_scope_are_denied(self):
        with patch.dict("os.environ", CONFIG):
            with patch("fairmount_api.private_read_api._configured_engine") as engine:
                for headers in (
                    {**self.cookie, "Origin": "https://other.example"},
                    {**self.cookie, "Sec-Fetch-Site": "cross-site"},
                    {**self.cookie, "X-Forwarded-For": "203.0.113.21"},
                    {"Cookie": f"{SESSION_COOKIE}={self.token}; {SESSION_COOKIE}={self.token}"},
                ):
                    with self.subTest(headers=headers):
                        response = self.client.get(URL, headers=headers)
                        self.assertIn(response.status_code, (401, 503))
                self.assertEqual(
                    self.client.get(
                        URL + "?account_id=" + str(uuid.uuid4()), headers=self.cookie
                    ).status_code,
                    400,
                )
                engine.assert_not_called()

    def test_reads_only_derived_self_wallet_after_session_touch_commit(self):
        account = uuid.uuid4()
        engine = MagicMock()
        with patch.dict("os.environ", CONFIG):
            with patch("fairmount_api.private_read_api._configured_engine", return_value=engine):
                with patch("fairmount_api.private_read_api.schema_ready", return_value=True):
                    with patch(
                        "fairmount_api.private_read_api.read_own_wallet",
                        return_value=WalletView(account, 75),
                    ) as read:
                        response = self.client.get(URL, headers=self.cookie)
        self.assertEqual(
            (response.status_code, response.json()),
            (200, {"account_id": str(account), "balance": 75}),
        )
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["Vary"], "Cookie")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(read.call_args.args[1], self.token)
        self.assertEqual(len(read.call_args.args), 2)  # no client target ID
        engine.begin.assert_called_once()
        self.assertNotIn(self.token, response.text)

    def test_revoked_or_disabled_session_is_generic_and_no_db_details_leak(self):
        engine = MagicMock()
        with patch.dict("os.environ", CONFIG):
            with patch("fairmount_api.private_read_api._configured_engine", return_value=engine):
                with patch("fairmount_api.private_read_api.schema_ready", return_value=True):
                    with patch(
                        "fairmount_api.private_read_api.read_own_wallet",
                        side_effect=ResourceUnavailable("Account disabled"),
                    ):
                        response = self.client.get(URL, headers=self.cookie)
                        self.assertEqual(
                            (response.status_code, response.json()),
                            (401, {"status": "unavailable"}),
                        )
                        self.assertNotIn("disabled", response.text)
                engine.begin.side_effect = SQLAlchemyError("private-db-secret")
                response = self.client.get(URL, headers=self.cookie)
                self.assertEqual(response.status_code, 503)
                self.assertNotIn("private-db-secret", response.text)


if __name__ == "__main__":
    unittest.main()
