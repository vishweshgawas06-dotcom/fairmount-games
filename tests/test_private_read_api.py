"""Opt-in direct-TLS private self-wallet and recent-bets HTTP boundaries."""

import datetime as dt
import secrets
import unittest
import uuid
from unittest.mock import MagicMock, patch

from fairmount_api.identity.http_boundary import SESSION_COOKIE
from fairmount_api.main import app
from fairmount_api.resource_reads import PrivateBetView, ResourceUnavailable, WalletView
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

URL = "/api/v1/me/wallet"
BETS_URL = "/api/v1/me/recent-bets"
PLAYER_URL = "/api/v1/players/{}/wallet"
ROSTER_URL = "/api/v1/me/players"
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


class RecentBetsAPITests(unittest.TestCase):
    setUp = PrivateReadAPITests.setUp

    def test_recent_bets_transport_and_scope_fail_closed(self):
        with patch.dict("os.environ", {"FAIRMOUNT_AUTH_EDGE_MODE": ""}):
            self.assertEqual(self.client.get(BETS_URL, headers=self.cookie).status_code, 503)
        with patch.dict("os.environ", CONFIG):
            plain = TestClient(app, base_url="http://game.example")
            self.assertEqual(plain.get(BETS_URL, headers=self.cookie).status_code, 503)
            self.assertEqual(self.client.get(BETS_URL).status_code, 401)
            with patch("fairmount_api.private_read_api._configured_engine") as engine:
                for headers in (
                    {**self.cookie, "Origin": "https://other.example"},
                    {**self.cookie, "Sec-Fetch-Site": "cross-site"},
                    {**self.cookie, "X-Forwarded-For": "203.0.113.21"},
                    {"Cookie": f"{SESSION_COOKIE}={self.token}; {SESSION_COOKIE}={self.token}"},
                ):
                    with self.subTest(headers=headers):
                        self.assertIn(
                            self.client.get(BETS_URL, headers=headers).status_code, (401, 503)
                        )
                self.assertEqual(
                    self.client.get(
                        BETS_URL + "?player_id=" + str(uuid.uuid4()), headers=self.cookie
                    ).status_code,
                    400,
                )
                engine.assert_not_called()

    def test_recent_bets_only_from_derived_live_player_session(self):
        bet = PrivateBetView(
            uuid.uuid4(),
            uuid.uuid4(),
            "straight:17",
            10,
            dt.datetime(2026, 10, 25, 10, 20, tzinfo=dt.UTC),
        )
        engine = MagicMock()
        with patch.dict("os.environ", CONFIG):
            with patch("fairmount_api.private_read_api._configured_engine", return_value=engine):
                with patch("fairmount_api.private_read_api.schema_ready", return_value=True):
                    with patch(
                        "fairmount_api.private_read_api.read_own_recent_bets", return_value=(bet,)
                    ) as read:
                        response = self.client.get(BETS_URL, headers=self.cookie)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "bets": [
                    {
                        "id": str(bet.id),
                        "round_id": str(bet.round_id),
                        "selection_key": bet.selection_key,
                        "accepted_stake": 10,
                        "accepted_at": "2026-10-25T10:20:00+00:00",
                    }
                ]
            },
        )
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["Vary"], "Cookie")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(read.call_args.args[1:], (self.token,))
        engine.begin.assert_called_once()
        self.assertNotIn(self.token, response.text)

    def test_recent_bets_revocation_schema_and_db_fail_generic(self):
        engine = MagicMock()
        with patch.dict("os.environ", CONFIG):
            with patch("fairmount_api.private_read_api._configured_engine", return_value=engine):
                with patch("fairmount_api.private_read_api.schema_ready", return_value=False):
                    self.assertEqual(
                        self.client.get(BETS_URL, headers=self.cookie).status_code, 503
                    )
                with patch("fairmount_api.private_read_api.schema_ready", return_value=True):
                    with patch(
                        "fairmount_api.private_read_api.read_own_recent_bets",
                        side_effect=ResourceUnavailable("disabled secret"),
                    ):
                        response = self.client.get(BETS_URL, headers=self.cookie)
                        self.assertEqual(response.status_code, 401)
                        self.assertEqual(response.json(), {"status": "unavailable"})
                        self.assertNotIn("secret", response.text)
                engine.begin.side_effect = SQLAlchemyError("database secret")
                response = self.client.get(BETS_URL, headers=self.cookie)
                self.assertEqual(response.status_code, 503)
                self.assertNotIn("secret", response.text)


class PlayerWalletAPITests(unittest.TestCase):
    setUp = PrivateReadAPITests.setUp

    def test_edge_rejects_disabled_http_cross_site_and_query_before_db(self):
        target = uuid.uuid4()
        url = PLAYER_URL.format(target)
        with patch.dict("os.environ", {"FAIRMOUNT_AUTH_EDGE_MODE": ""}):
            self.assertEqual(self.client.get(url, headers=self.cookie).status_code, 503)
        with patch.dict("os.environ", CONFIG):
            plain = TestClient(app, base_url="http://game.example")
            self.assertEqual(plain.get(url, headers=self.cookie).status_code, 503)
            self.assertEqual(self.client.get(url).status_code, 401)
            with patch("fairmount_api.private_read_api._configured_engine") as engine:
                for headers in (
                    {**self.cookie, "Origin": "https://other.example"},
                    {**self.cookie, "Sec-Fetch-Site": "cross-site"},
                    {**self.cookie, "X-Forwarded-For": "203.0.113.21"},
                ):
                    with self.subTest(headers=headers):
                        self.assertIn(self.client.get(url, headers=headers).status_code, (401, 503))
                self.assertEqual(
                    self.client.get(
                        url + "?agent_id=" + str(uuid.uuid4()), headers=self.cookie
                    ).status_code,
                    400,
                )
                for invalid in ("invalid", target.hex, str(target).upper()):
                    with self.subTest(invalid=invalid):
                        self.assertEqual(
                            self.client.get(
                                PLAYER_URL.format(invalid), headers=self.cookie
                            ).status_code,
                            404,
                        )
                engine.assert_not_called()

    def test_target_is_reauthorized_in_data_layer_and_denials_are_indistinguishable(self):
        target = uuid.uuid4()
        engine = MagicMock()
        with patch.dict("os.environ", CONFIG):
            with patch("fairmount_api.private_read_api._configured_engine", return_value=engine):
                with patch("fairmount_api.private_read_api.schema_ready", return_value=True):
                    with patch(
                        "fairmount_api.private_read_api.read_player_wallet",
                        return_value=WalletView(target, 75),
                    ) as read:
                        response = self.client.get(PLAYER_URL.format(target), headers=self.cookie)
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(
                            response.json(), {"account_id": str(target), "balance": 75}
                        )
                        self.assertEqual(read.call_args.args[1:], (self.token, target))
                        self.assertEqual(response.headers["Cache-Control"], "no-store")
                        self.assertEqual(response.headers["Vary"], "Cookie")
                        engine.begin.assert_called_once()
                    with patch(
                        "fairmount_api.private_read_api.read_player_wallet",
                        side_effect=ResourceUnavailable("assigned elsewhere"),
                    ):
                        for forbidden in (target, uuid.uuid4()):
                            denied = self.client.get(
                                PLAYER_URL.format(forbidden), headers=self.cookie
                            )
                            self.assertEqual(
                                (denied.status_code, denied.json()),
                                (404, {"status": "unavailable"}),
                            )
                            self.assertNotIn("elsewhere", denied.text)
                engine.begin.side_effect = SQLAlchemyError("secret-db")
                response = self.client.get(PLAYER_URL.format(target), headers=self.cookie)
                self.assertEqual(response.status_code, 503)
                self.assertNotIn("secret-db", response.text)


class VisiblePlayersAPITests(unittest.TestCase):
    setUp = PrivateReadAPITests.setUp

    def test_edge_rejects_proxy_cross_site_missing_cookie_and_client_scope(self):
        with patch.dict("os.environ", {"FAIRMOUNT_AUTH_EDGE_MODE": ""}):
            self.assertEqual(self.client.get(ROSTER_URL, headers=self.cookie).status_code, 503)
        with patch.dict("os.environ", CONFIG):
            plain = TestClient(app, base_url="http://game.example")
            self.assertEqual(plain.get(ROSTER_URL, headers=self.cookie).status_code, 503)
            self.assertEqual(self.client.get(ROSTER_URL).status_code, 401)
            with patch("fairmount_api.private_read_api._configured_engine") as engine:
                for headers in (
                    {**self.cookie, "Origin": "https://other.example"},
                    {**self.cookie, "Sec-Fetch-Site": "cross-site"},
                    {**self.cookie, "X-Forwarded-For": "203.0.113.21"},
                    {"Cookie": f"{SESSION_COOKIE}={self.token}; {SESSION_COOKIE}={self.token}"},
                ):
                    with self.subTest(headers=headers):
                        self.assertIn(
                            self.client.get(ROSTER_URL, headers=headers).status_code,
                            (401, 503),
                        )
                self.assertEqual(
                    self.client.get(
                        ROSTER_URL + "?agent_id=" + str(uuid.uuid4()), headers=self.cookie
                    ).status_code,
                    400,
                )
                engine.assert_not_called()

    def test_projection_is_only_authorized_ids_and_failures_are_generic(self):
        first, second = uuid.uuid4(), uuid.uuid4()
        engine = MagicMock()
        with patch.dict("os.environ", CONFIG):
            with patch("fairmount_api.private_read_api._configured_engine", return_value=engine):
                with patch("fairmount_api.private_read_api.schema_ready", return_value=True):
                    with patch(
                        "fairmount_api.private_read_api.list_visible_player_ids",
                        return_value=(first, second),
                    ) as read:
                        response = self.client.get(ROSTER_URL, headers=self.cookie)
                    self.assertEqual(
                        (response.status_code, response.json()),
                        (200, {"player_ids": [str(first), str(second)]}),
                    )
                    self.assertEqual(read.call_args.args[1:], (self.token,))
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                    self.assertEqual(response.headers["Vary"], "Cookie")
                    self.assertNotIn(self.token, response.text)
                    with patch(
                        "fairmount_api.private_read_api.list_visible_player_ids",
                        side_effect=ResourceUnavailable("session private detail"),
                    ):
                        denied = self.client.get(ROSTER_URL, headers=self.cookie)
                        self.assertEqual(
                            (denied.status_code, denied.json()), (401, {"status": "unavailable"})
                        )
                        self.assertNotIn("private detail", denied.text)
                engine.begin.side_effect = SQLAlchemyError("private-db-secret")
                unavailable = self.client.get(ROSTER_URL, headers=self.cookie)
                self.assertEqual(unavailable.status_code, 503)
                self.assertNotIn("private-db-secret", unavailable.text)


if __name__ == "__main__":
    unittest.main()
