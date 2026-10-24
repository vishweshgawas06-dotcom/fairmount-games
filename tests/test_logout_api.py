"""Direct-TLS logout requires same-origin CSRF, commits revocation, then clears cookies."""

import secrets
import unittest
from unittest.mock import MagicMock, patch

from fairmount_api.identity.http_boundary import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE
from fairmount_api.main import app
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

URL = "/api/v1/auth/logout"
CONFIG = {
    "FAIRMOUNT_AUTH_EDGE_MODE": "direct-tls",
    "FAIRMOUNT_PUBLIC_ORIGIN": "https://game.example",
}


class LogoutAPITests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(
            app, base_url="https://game.example", client=("203.0.113.17", 51000)
        )
        self.token = secrets.token_urlsafe(32)
        self.csrf = secrets.token_urlsafe(32)
        self.headers = {
            "Origin": "https://game.example",
            "Cookie": f"{SESSION_COOKIE}={self.token}; {CSRF_COOKIE}={self.csrf}",
            CSRF_HEADER: self.csrf,
        }

    def test_disabled_mode_or_plain_http_does_not_revoke(self):
        with patch.dict("os.environ", {"FAIRMOUNT_AUTH_EDGE_MODE": ""}):
            self.assertEqual(self.client.post(URL, headers=self.headers).status_code, 503)
        with patch.dict("os.environ", CONFIG):
            plain = TestClient(app, base_url="http://game.example", client=("203.0.113.17", 51000))
            self.assertEqual(plain.post(URL, headers=self.headers).status_code, 503)

    def test_missing_or_mismatched_csrf_origin_and_ambiguous_cookies_are_denied(self):
        with patch.dict("os.environ", CONFIG):
            with patch("fairmount_api.identity.login_api._configured_engine") as engine:
                cases = (
                    {**self.headers, CSRF_HEADER: secrets.token_urlsafe(32)},
                    {k: v for k, v in self.headers.items() if k != CSRF_HEADER},
                    {**self.headers, "Origin": "https://evil.example"},
                    {
                        **self.headers,
                        "Cookie": self.headers["Cookie"] + f"; {SESSION_COOKIE}={self.token}",
                    },
                )
                for headers in cases:
                    with self.subTest(headers=headers):
                        response = self.client.post(URL, headers=headers)
                        self.assertEqual(response.status_code, 403)
                        self.assertNotIn("set-cookie", response.headers)
                engine.assert_not_called()

    def test_idempotent_revoke_then_clear_only_after_committed_transaction(self):
        engine = MagicMock()
        with patch.dict("os.environ", CONFIG):
            with patch("fairmount_api.identity.login_api._configured_engine", return_value=engine):
                with patch("fairmount_api.identity.login_api.schema_ready", return_value=True):
                    with patch(
                        "fairmount_api.identity.login_api.revoke_presented_session"
                    ) as revoke:
                        for found in (True, False):
                            revoke.return_value = found
                            response = self.client.post(URL, headers=self.headers)
                            self.assertEqual(
                                (response.status_code, response.json()),
                                (200, {"status": "signed_out"}),
                            )
                            self.assertEqual(response.headers["Cache-Control"], "no-store")
                            self.assertEqual(revoke.call_args.args[1], self.token)
                            cookies = response.headers.get_list("set-cookie")
                            self.assertEqual(len(cookies), 2)
                            self.assertTrue(all("Max-Age=0" in cookie for cookie in cookies))
                            self.assertIn(SESSION_COOKIE, cookies[0])
                            self.assertIn(CSRF_COOKIE, cookies[1])
                            self.assertNotIn(self.token, response.text)
                        self.assertEqual(engine.begin.call_count, 2)

    def test_database_error_keeps_cookie_until_revoke_can_commit(self):
        engine = MagicMock()
        engine.begin.side_effect = SQLAlchemyError("private database failure")
        with patch.dict("os.environ", CONFIG):
            with patch("fairmount_api.identity.login_api._configured_engine", return_value=engine):
                response = self.client.post(URL, headers=self.headers)
        self.assertEqual((response.status_code, response.json()), (503, {"status": "unavailable"}))
        self.assertNotIn("set-cookie", response.headers)
        self.assertNotIn("private database failure", response.text)


if __name__ == "__main__":
    unittest.main()
