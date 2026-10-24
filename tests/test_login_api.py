"""HTTP direct-TLS login orchestration; private issuers have separate DB tests."""

import secrets
import unittest
import uuid
from unittest.mock import MagicMock, patch

from fairmount_api.identity.auth_attempts import AuthAttemptOutcome
from fairmount_api.identity.http_boundary import CSRF_COOKIE, SESSION_COOKIE
from fairmount_api.identity.member_login import IssuedMemberSession
from fairmount_api.identity.owner_login import IssuedOwnerSession
from fairmount_api.main import app
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

URL = "/api/v1/auth/login"
ENABLED = {
    "FAIRMOUNT_AUTH_EDGE_MODE": "direct-tls",
    "FAIRMOUNT_PUBLIC_ORIGIN": "https://game.example",
}
KEY = b"test-only-hmac-separate-from-mfa!"


class LoginAPITests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(
            app, base_url="https://game.example", client=("203.0.113.9", 55000)
        )
        self.payload = {
            "role": "PLAYER",
            "identifier": "exampleplayer",
            "password": "correct horse battery",
        }

    def post(self, **options):
        return self.client.post(
            URL, json=self.payload, headers={"Origin": "https://game.example"}, **options
        )

    def test_disabled_by_default_and_no_preview_http_bypass(self):
        with patch.dict(
            "os.environ", {"FAIRMOUNT_AUTH_EDGE_MODE": "", "FAIRMOUNT_PUBLIC_ORIGIN": ""}
        ):
            self.assertEqual(self.post().status_code, 503)
        with patch.dict("os.environ", ENABLED):
            response = TestClient(
                app, base_url="http://game.example", client=("203.0.113.9", 55000)
            ).post(URL, json=self.payload, headers={"Origin": "https://game.example"})
        self.assertEqual((response.status_code, response.json()), (503, {"status": "unavailable"}))
        self.assertNotIn("set-cookie", response.headers)

    def test_reject_cross_site_forwarded_or_unknown_peer_before_credentials(self):
        with patch.dict("os.environ", ENABLED):
            with patch("fairmount_api.identity.login_api._configured_engine") as engine:
                cross_site = self.client.post(
                    URL, json=self.payload, headers={"Origin": "https://other.example"}
                )
                self.assertEqual(cross_site.status_code, 403)
                for header in ("X-Forwarded-For", "Forwarded", "X-Real-IP"):
                    with self.subTest(header=header):
                        response = self.client.post(
                            URL,
                            json=self.payload,
                            headers={"Origin": "https://game.example", header: "203.0.113.9"},
                        )
                        self.assertEqual(response.status_code, 503)
                unknown = TestClient(
                    app, base_url="https://game.example", client=("testclient", 55000)
                ).post(URL, json=self.payload, headers={"Origin": "https://game.example"})
                self.assertEqual(unknown.status_code, 503)
                engine.assert_not_called()

    def test_reject_bounded_malformed_json_without_creating_a_session(self):
        with patch.dict("os.environ", ENABLED):
            with patch("fairmount_api.identity.login_api._configured_engine") as engine:
                for payload in (
                    {"role": "ADMIN", "identifier": "x", "password": "x"},
                    {"role": "PLAYER", "identifier": "x", "password": "x", "extra": "x"},
                ):
                    response = self.client.post(
                        URL, json=payload, headers={"Origin": "https://game.example"}
                    )
                    self.assertEqual(response.status_code, 400)
                response = self.client.post(
                    URL,
                    content=b"{" + b"x" * 4097,
                    headers={"Origin": "https://game.example", "Content-Type": "application/json"},
                )
                self.assertEqual(response.status_code, 400)
                response = self.client.post(
                    URL,
                    content=b'{"role":"PLAYER","role":"OWNER"}',
                    headers={"Origin": "https://game.example", "Content-Type": "application/json"},
                )
                self.assertEqual(response.status_code, 400)
                engine.assert_not_called()

    def test_commit_denial_and_success_before_cookie_issue(self):
        engine = MagicMock()
        token = secrets.token_urlsafe(32)
        issued = IssuedMemberSession(uuid.uuid4(), uuid.uuid4(), "PLAYER", token)
        with patch.dict("os.environ", ENABLED):
            with patch("fairmount_api.identity.login_api._configured_engine", return_value=engine):
                with patch("fairmount_api.identity.login_api.load_auth_hmac_key", return_value=KEY):
                    with patch("fairmount_api.identity.login_api.schema_ready", return_value=True):
                        with patch(
                            "fairmount_api.identity.login_api.guarded_member_login"
                        ) as guard:
                            guard.return_value = AuthAttemptOutcome(False, False)
                            denied = self.post()
                            self.assertEqual(
                                (denied.status_code, denied.json()), (401, {"status": "denied"})
                            )
                            self.assertNotIn("set-cookie", denied.headers)
                            guard.return_value = AuthAttemptOutcome(False, True)
                            blocked = self.post()
                            self.assertEqual(blocked.json(), denied.json())
                            guard.return_value = AuthAttemptOutcome(True, False, issued)
                            success = self.post()
                            self.assertEqual(
                                (success.status_code, success.json()),
                                (200, {"status": "authenticated"}),
                            )
                            self.assertNotIn(token, success.text)
                            self.assertEqual(success.headers["Cache-Control"], "no-store")
                            cookies = success.headers.get_list("set-cookie")
                            self.assertEqual(len(cookies), 2)
                            self.assertIn(SESSION_COOKIE, cookies[0])
                            self.assertIn("HttpOnly", cookies[0])
                            self.assertIn("Secure", cookies[0])
                            self.assertIn(CSRF_COOKIE, cookies[1])
                            self.assertNotIn("HttpOnly", cookies[1])
                            self.assertEqual(engine.begin.call_count, 3)
                            self.assertEqual(guard.call_args.kwargs["source_ip"], "203.0.113.9")
                            self.assertEqual(guard.call_args.kwargs["pepper"], KEY)

    def test_owner_requires_keyring_and_mfa_without_exposing_factor(self):
        engine = MagicMock()
        token = secrets.token_urlsafe(32)
        self.payload = {
            "role": "OWNER",
            "identifier": "owner",
            "password": "correct horse battery",
            "factor_kind": "totp",
            "code": "123456",
        }
        with patch.dict("os.environ", ENABLED):
            with patch("fairmount_api.identity.login_api._configured_engine", return_value=engine):
                with patch("fairmount_api.identity.login_api.load_auth_hmac_key", return_value=KEY):
                    with patch(
                        "fairmount_api.identity.login_api.load_mfa_keyring",
                        return_value=MagicMock(),
                    ):
                        with patch(
                            "fairmount_api.identity.login_api.schema_ready", return_value=True
                        ):
                            with patch(
                                "fairmount_api.identity.login_api.guarded_owner_login",
                                return_value=AuthAttemptOutcome(
                                    True,
                                    False,
                                    IssuedOwnerSession(uuid.uuid4(), uuid.uuid4(), token),
                                ),
                            ) as guard:
                                response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Max-Age=28800", response.headers.get_list("set-cookie")[0])
        self.assertNotIn("123456", response.text)
        self.assertEqual(guard.call_args.kwargs["factor_kind"], "totp")
        self.assertEqual(guard.call_args.kwargs["code"], "123456")

    def test_key_or_database_errors_are_generic_and_never_set_cookies(self):
        engine = MagicMock()
        with patch.dict("os.environ", ENABLED):
            with patch("fairmount_api.identity.login_api._configured_engine", return_value=engine):
                with patch(
                    "fairmount_api.identity.login_api.load_auth_hmac_key",
                    side_effect=ValueError("private key file"),
                ):
                    response = self.post()
                    self.assertEqual(response.status_code, 503)
                    self.assertNotIn("private key", response.text)
                with patch("fairmount_api.identity.login_api.load_auth_hmac_key", return_value=KEY):
                    engine.begin.side_effect = SQLAlchemyError("secret-dsn")
                    response = self.post()
                    self.assertEqual(response.status_code, 503)
                    self.assertNotIn("secret-dsn", response.text)
                    self.assertNotIn("set-cookie", response.headers)


if __name__ == "__main__":
    unittest.main()
