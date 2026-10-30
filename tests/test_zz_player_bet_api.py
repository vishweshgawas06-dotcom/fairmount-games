"""Opt-in direct-TLS player bet write against PostgreSQL; no proxy mode.

Every fixture commits because admission, ledger and audit rows are immutable and
the route commits before it responds. This module is named ``test_zz_`` so it
runs after every rollback-isolated module, following the existing ``test_z_``
committed-flow convention: after it, a single OWNER row and one OPEN round
remain, which is harmless only at the end of a suite that starts from a reset
database.
"""

import os
import secrets
import unittest
import uuid
from unittest.mock import patch

from fairmount_api.db.models import (
    Account,
    AccountSession,
    AccountWallet,
    GameReserve,
    RouletteBet,
    RouletteRound,
)
from fairmount_api.identity.http_boundary import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE
from fairmount_api.identity.session_validation import session_token_digest
from fairmount_api.main import app
from fairmount_api.point_accounting import issue_owner_points, transfer_owner_points
from fairmount_api.readiness import _configured_engine
from fairmount_api.reserve_funding import fund_game_reserve
from fairmount_api.roulette.round_clock import open_round
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, insert, select, text, update

from infrastructure.local_db_url import local_database_url

ORIGIN = "https://game.example"
CONFIG = {"FAIRMOUNT_AUTH_EDGE_MODE": "direct-tls", "FAIRMOUNT_PUBLIC_ORIGIN": ORIGIN}
PLAYER_START = 100
RESERVE_START = 340


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "Disposable PostgreSQL test DB required"
)
class PlayerBetHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Exactly one OWNER account and one unrevoked session per account may
        # exist, so the owner fixture is created once for the whole class.
        cls.engine = create_engine(local_database_url(test=True))
        with cls.engine.begin() as connection:
            # An earlier committed-flow module may already own the single OWNER
            # row; reuse it and revoke any stale session before issuing a fixture
            # session (one unrevoked session per account is enforced).
            cls.owner = connection.scalar(
                select(Account.id).where(Account.role == "OWNER")
            )
            if cls.owner is None:
                cls.owner = connection.execute(
                    insert(Account.__table__).values(role="OWNER").returning(Account.id)
                ).scalar_one()
            connection.execute(
                update(AccountSession.__table__)
                .where(
                    AccountSession.account_id == cls.owner,
                    AccountSession.revoked_at.is_(None),
                )
                .values(revoked_at=func.now())
            )
            cls.owner_token = cls.session(connection, cls.owner, "OWNER")

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        url = local_database_url(test=True).render_as_string(hide_password=False)
        self.environment = patch.dict(os.environ, {**CONFIG, "FAIRMOUNT_API_DATABASE_URL": url})
        self.environment.start()
        _configured_engine.cache_clear()
        with self.engine.begin() as connection:
            self.player = self.account(connection, "PLAYER")
            self.player_token = self.session(connection, self.player, "PLAYER")
            owner_token = self.owner_token
            issue_owner_points(
                connection,
                owner_token,
                amount=500,
                reason="approved issuance",
                idempotency_key=f"issue-{uuid.uuid4()}",
            )
            transfer_owner_points(
                connection,
                owner_token,
                member_account_id=self.player,
                amount=PLAYER_START,
                to_member=True,
                reason="player allocation",
                idempotency_key=f"transfer-{uuid.uuid4()}",
            )
            fund_game_reserve(
                connection,
                owner_token,
                amount=RESERVE_START,
                reason="reserve funding",
                idempotency_key=f"reserve-{uuid.uuid4()}",
            )
            # Exactly one round may be OPEN globally; reuse it across tests.
            self.round_id = connection.scalar(
                select(RouletteRound.id).where(RouletteRound.state == "OPEN")
            ) or open_round(connection)
        # The funded reserve is a global singleton shared by every test.
        self.reserve_baseline = self.reserve()
        self.csrf = secrets.token_urlsafe(32)
        self.client = TestClient(
            app,
            base_url=ORIGIN,
            client=("203.0.113.61", 50610),
            cookies={SESSION_COOKIE: self.player_token, CSRF_COOKIE: self.csrf},
        )

    def tearDown(self):
        engine = _configured_engine()
        if engine is not None:
            engine.dispose()
        _configured_engine.cache_clear()
        self.environment.stop()

    @staticmethod
    def account(connection, role):
        return connection.execute(
            insert(Account.__table__).values(role=role).returning(Account.id)
        ).scalar_one()

    @staticmethod
    def session(connection, account, role):
        token = secrets.token_urlsafe(32)
        is_owner = role == "OWNER"
        connection.execute(
            insert(AccountSession.__table__).values(
                account_id=account,
                role_at_issue=role,
                token_digest=session_token_digest(token),
                issued_at=func.now() - text("interval '5 minutes'") if is_owner else func.now(),
                last_seen_at=func.now(),
                idle_expires_at=func.now()
                + text("interval '15 minutes'" if is_owner else "interval '30 minutes'"),
                absolute_expires_at=func.now()
                + text("interval '7 hours 55 minutes'" if is_owner else "interval '24 hours'"),
                mfa_verified_at=func.now() - text("interval '5 minutes'") if is_owner else None,
            )
        )
        return token

    def url(self, round_id=None):
        return f"/api/v1/rounds/{round_id or self.round_id}/bets"

    def headers(self, key=None, **extra):
        return {
            "origin": ORIGIN,
            CSRF_HEADER: self.csrf,
            "idempotency-key": key or str(uuid.uuid4()),
            **extra,
        }

    def wallet(self):
        with self.engine.connect() as connection:
            return connection.scalar(
                select(AccountWallet.balance).where(AccountWallet.account_id == self.player)
            )

    def reserve(self):
        with self.engine.connect() as connection:
            return connection.scalar(select(GameReserve.balance).where(GameReserve.id == 1))

    def bets(self):
        with self.engine.connect() as connection:
            return connection.execute(
                select(RouletteBet.id, RouletteBet.accepted_stake, RouletteBet.selection_key).where(
                    RouletteBet.round_id == self.round_id,
                    RouletteBet.player_account_id == self.player,
                )
            ).all()

    def test_one_valid_bet_debits_wallet_and_credits_reserve_once(self):
        response = self.client.post(
            self.url(),
            json={"selection_key": "straight:17", "stake": 10},
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(
            (payload["requested"], payload["accepted"], payload["unaccepted"], payload["replayed"]),
            (10, 10, 0, False),
        )
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["vary"], "Cookie")
        self.assertEqual(
            (self.wallet(), self.reserve() - self.reserve_baseline), (PLAYER_START - 10, 10)
        )
        self.assertEqual(len(self.bets()), 1)
        for private in ("password", "token", "csrf", "credential"):
            self.assertNotIn(private, response.text.lower())

    def test_same_key_replays_without_a_second_debit(self):
        key = str(uuid.uuid4())
        first = self.client.post(
            self.url(),
            json={"selection_key": "straight:17", "stake": 10},
            headers=self.headers(key),
        )
        second = self.client.post(
            self.url(),
            json={"selection_key": "straight:17", "stake": 10},
            headers=self.headers(key),
        )
        self.assertEqual((first.status_code, second.status_code), (200, 200))
        self.assertFalse(first.json()["replayed"])
        self.assertTrue(second.json()["replayed"])
        self.assertEqual(first.json()["bet_id"], second.json()["bet_id"])
        self.assertEqual(
            (self.wallet(), self.reserve() - self.reserve_baseline), (PLAYER_START - 10, 10)
        )
        self.assertEqual(len(self.bets()), 1)

    def test_reused_key_with_a_different_request_conflicts(self):
        key = str(uuid.uuid4())
        self.client.post(
            self.url(),
            json={"selection_key": "straight:17", "stake": 10},
            headers=self.headers(key),
        )
        changed = self.client.post(
            self.url(),
            json={"selection_key": "straight:18", "stake": 10},
            headers=self.headers(key),
        )
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(changed.json(), {"status": "conflict"})
        self.assertEqual(
            (self.wallet(), self.reserve() - self.reserve_baseline), (PLAYER_START - 10, 10)
        )
        self.assertEqual(len(self.bets()), 1)

    def test_equivalent_selection_spelling_is_the_same_request(self):
        key = str(uuid.uuid4())
        self.client.post(
            self.url(),
            json={"selection_key": "split:17-20", "stake": 10},
            headers=self.headers(key),
        )
        replay = self.client.post(
            self.url(),
            json={"selection_key": "SPLIT:20-17", "stake": 10},
            headers=self.headers(key),
        )
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.json()["replayed"])

    def test_boundary_and_schema_denials_write_nothing(self):
        key = str(uuid.uuid4())
        cases = (
            ("cross-origin", {"headers": self.headers(key, origin="https://evil.example")}),
            ("no-csrf", {"headers": {"origin": ORIGIN, "idempotency-key": key}}),
            ("no-key", {"headers": {"origin": ORIGIN, CSRF_HEADER: self.csrf}}),
            ("query", {"headers": self.headers(key), "params": {"stake": "10"}}),
            (
                "form",
                {
                    "data": {"selection_key": "straight:17", "stake": "10"},
                    "headers": self.headers(key),
                },
            ),
            (
                "extra-field",
                {
                    "json": {
                        "selection_key": "straight:17",
                        "stake": 10,
                        "player_id": str(self.player),
                    },
                    "headers": self.headers(key),
                },
            ),
            (
                "bad-chip",
                {
                    "json": {"selection_key": "straight:17", "stake": 7},
                    "headers": self.headers(key),
                },
            ),
            (
                "bad-selection",
                {
                    "json": {"selection_key": "straight:99", "stake": 10},
                    "headers": self.headers(key),
                },
            ),
            (
                "oversized",
                {
                    "content": b'{"selection_key": "' + b"x" * 5000 + b'", "stake": 10}',
                    "headers": self.headers(key, **{"content-type": "application/json"}),
                },
            ),
        )
        for name, kwargs in cases:
            with self.subTest(name=name):
                response = self.client.post(self.url(), **kwargs)
                self.assertIn(response.status_code, (400, 401), response.text)
                self.assertEqual(response.json(), {"status": "unavailable"})
                self.assertNotIn(self.player_token, response.text)
        self.assertEqual(self.bets(), [])
        self.assertEqual((self.wallet(), self.reserve() - self.reserve_baseline), (PLAYER_START, 0))

    def test_unaffordable_full_stake_is_rejected_without_partial_acceptance(self):
        response = self.client.post(
            self.url(),
            json={"selection_key": "straight:17", "stake": PLAYER_START + 5},
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"status": "unavailable"})
        self.assertEqual(self.bets(), [])
        self.assertEqual((self.wallet(), self.reserve() - self.reserve_baseline), (PLAYER_START, 0))

    def test_unknown_round_and_malformed_ids_are_not_disclosed(self):
        missing = uuid.uuid4()
        self.assertEqual(
            self.client.post(
                self.url(missing), json={"selection_key": "red", "stake": 5}, headers=self.headers()
            ).status_code,
            409,
        )
        for bad in ("not-a-uuid", str(self.round_id).upper()):
            with self.subTest(round_id=bad):
                self.assertEqual(
                    self.client.post(
                        self.url(bad),
                        json={"selection_key": "red", "stake": 5},
                        headers=self.headers(),
                    ).status_code,
                    404,
                )
        self.assertEqual(self.bets(), [])

    def test_only_post_is_routed_and_other_methods_are_not_accepted(self):
        for method in ("get", "put", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(self.url(), headers=self.headers())
                self.assertEqual(response.status_code, 405)

    def test_route_is_disabled_without_direct_tls_configuration(self):
        for config in (
            {},
            {"FAIRMOUNT_AUTH_EDGE_MODE": "proxy", "FAIRMOUNT_PUBLIC_ORIGIN": ORIGIN},
        ):
            with self.subTest(config=config):
                engine = _configured_engine()
                if engine is not None:
                    engine.dispose()
                _configured_engine.cache_clear()
                with patch.dict(os.environ, config, clear=False):
                    for name in ("FAIRMOUNT_AUTH_EDGE_MODE", "FAIRMOUNT_PUBLIC_ORIGIN"):
                        if name not in config:
                            os.environ.pop(name, None)
                    try:
                        response = self.client.post(
                            self.url(),
                            json={"selection_key": "straight:17", "stake": 10},
                            headers=self.headers(),
                        )
                        self.assertEqual(response.status_code, 503, response.text)
                    finally:
                        os.environ.update(CONFIG)
                        _configured_engine.cache_clear()
        self.assertEqual(self.bets(), [])


if __name__ == "__main__":
    unittest.main()
