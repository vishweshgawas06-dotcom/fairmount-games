"""Committed owner HTTP lifecycle checks; run after rollback-isolated modules."""

import base64
import os
import secrets
import tempfile
import unittest
import uuid
from unittest.mock import patch

from fairmount_api.db.models import (
    Account,
    AccountCredential,
    AccountSession,
    AgentAssignment,
    OperatorWriteReceipt,
    SecurityEvent,
)
from fairmount_api.identity.credentials import initial_secret_digest
from fairmount_api.identity.http_boundary import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE
from fairmount_api.identity.provisioning import provision_agent, provision_player
from fairmount_api.identity.session_validation import session_token_digest
from fairmount_api.main import app
from fairmount_api.readiness import _configured_engine
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, insert, select, text, update
from sqlalchemy.exc import IntegrityError

from infrastructure.local_db_url import local_database_url

ORIGIN = "https://game.example"
BASE = "/api/v1/operator/"


class OperatorClosedTests(unittest.TestCase):
    def test_all_routes_fail_closed_without_direct_tls(self):
        with patch.dict(os.environ, {"FAIRMOUNT_AUTH_EDGE_MODE": "disabled"}):
            with TestClient(app) as client:
                for route in (
                    "agents",
                    "players",
                    "assignments",
                    "assignments/remove",
                    "accounts/status",
                ):
                    response = client.post(BASE + route, json={})
                    self.assertEqual(response.status_code, 503)
                    self.assertEqual(response.headers["cache-control"], "no-store")


@unittest.skipUnless(os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL opt-in")
class OperatorHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(local_database_url(test=True))

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        path = os.path.join(self.temp.name, "hmac.key")
        with open(path, "wb") as handle:
            handle.write(base64.b64encode(secrets.token_bytes(32)) + b"\n")
        os.chmod(path, 0o600)
        self.environment = patch.dict(
            os.environ,
            {
                "FAIRMOUNT_AUTH_EDGE_MODE": "direct-tls",
                "FAIRMOUNT_PUBLIC_ORIGIN": ORIGIN,
                "FAIRMOUNT_AUTH_HMAC_KEY_FILE": path,
                "FAIRMOUNT_API_DATABASE_URL": local_database_url(test=True).render_as_string(
                    hide_password=False
                ),
            },
        )
        self.environment.start()
        _configured_engine.cache_clear()
        self.csrf = secrets.token_urlsafe(32)
        self.name = "user_" + uuid.uuid4().hex[:15]
        with self.engine.begin() as connection:
            self.owner = connection.scalar(select(Account.id).where(Account.role == "OWNER"))
            if self.owner is None:
                self.owner = connection.execute(
                    insert(Account.__table__).values(role="OWNER").returning(Account.id)
                ).scalar_one()
            self.token = self.session(connection, self.owner, "OWNER")
        self.client = TestClient(
            app,
            base_url=ORIGIN,
            client=("203.0.113.73", 50432),
            cookies={SESSION_COOKIE: self.token, CSRF_COOKIE: self.csrf},
        )

    def tearDown(self):
        self.client.close()
        engine = _configured_engine()
        if engine is not None:
            engine.dispose()
        _configured_engine.cache_clear()
        self.environment.stop()
        self.temp.cleanup()

    @staticmethod
    def session(connection, account, role):
        connection.execute(
            update(AccountSession.__table__)
            .where(AccountSession.account_id == account, AccountSession.revoked_at.is_(None))
            .values(revoked_at=func.now())
        )
        token = secrets.token_urlsafe(32)
        owner = role == "OWNER"
        connection.execute(
            insert(AccountSession.__table__).values(
                account_id=account,
                role_at_issue=role,
                token_digest=session_token_digest(token),
                issued_at=func.now() - text("interval '5 minutes'") if owner else func.now(),
                last_seen_at=func.now(),
                idle_expires_at=func.now()
                + text("interval '15 minutes'" if owner else "interval '30 minutes'"),
                absolute_expires_at=func.now()
                + text(
                    "interval '7 hours 55 minutes'"
                    if owner
                    else "interval '12 hours'"
                    if role == "AGENT"
                    else "interval '24 hours'"
                ),
                mfa_verified_at=func.now() - text("interval '5 minutes'") if owner else None,
            )
        )
        return token

    def headers(self, key=None, **extra):
        return {
            "origin": ORIGIN,
            CSRF_HEADER: self.csrf,
            "idempotency-key": key or str(uuid.uuid4()),
            **extra,
        }

    def post(self, route, body, key=None, **headers):
        return self.client.post(BASE + route, json=body, headers=self.headers(key, **headers))

    def fixtures(self):
        with self.engine.begin() as connection:
            agent = provision_agent(connection, self.token)
            player = provision_player(connection, self.token, username=self.name)
        return agent, player

    def event_count(self, target, event):
        with self.engine.connect() as connection:
            return connection.scalar(
                select(func.count())
                .select_from(SecurityEvent)
                .where(SecurityEvent.target_account_id == target, SecurityEvent.event_type == event)
            )

    def test_provision_commit_secret_digest_and_nonsecret_replay(self):
        for route, body, login in (
            ("agents", {}, "agent_id"),
            ("players", {"username": self.name}, "username"),
        ):
            key = str(uuid.uuid4())
            first = self.post(route, body, key)
            self.assertEqual(first.status_code, 201, first.text)
            payload = first.json()
            target = uuid.UUID(payload["account_id"])
            with self.engine.connect() as connection:
                credential = connection.execute(
                    select(AccountCredential).where(AccountCredential.account_id == target)
                ).one()
                self.assertEqual(
                    credential.initial_secret_digest, initial_secret_digest(payload["secret"])
                )
                self.assertIsNone(credential.password_hash)
                stored = connection.scalar(
                    select(OperatorWriteReceipt.response).where(
                        OperatorWriteReceipt.owner_account_id == self.owner,
                        OperatorWriteReceipt.request_key == uuid.UUID(key),
                    )
                )
                self.assertNotIn("secret", stored)
                self.assertNotIn(payload["secret"], str(stored))
            replay = self.post(route, body, key)
            self.assertEqual(replay.status_code, 200, replay.text)
            self.assertEqual(replay.json()[login], payload[login])
            self.assertEqual(replay.json()["account_id"], payload["account_id"])
            self.assertTrue(replay.json()["replayed"])
            self.assertNotIn("secret", replay.json())
            self.assertEqual(self.event_count(target, "INITIAL_CREDENTIAL_ISSUED"), 1)
            self.assertEqual(first.headers["cache-control"], "no-store")
            self.assertEqual(first.headers["vary"], "Cookie")

    def test_reused_key_different_body_or_action_is_conflict(self):
        key = str(uuid.uuid4())
        self.assertEqual(self.post("players", {"username": self.name}, key).status_code, 201)
        self.assertEqual(self.post("players", {"username": self.name + "x"}, key).status_code, 409)
        self.assertEqual(self.post("agents", {}, key).status_code, 409)

    def test_assignment_unassignment_and_reassignment_are_committed(self):
        agent, player = self.fixtures()
        body = {"username": self.name, "agent_id": agent.login_id}
        first = self.post("assignments", body)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(
            self.post("assignments", body).json()["assignment_id"], first.json()["assignment_id"]
        )
        with self.engine.begin() as connection:
            second = provision_agent(connection, self.token)
        self.assertEqual(
            self.post("assignments", {**body, "agent_id": second.login_id}).status_code, 200
        )
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(AgentAssignment).where(
                    AgentAssignment.player_account_id == player.account_id
                )
            ).all()
            self.assertEqual(len(rows), 2)
            self.assertEqual(sum(row.ended_at is None for row in rows), 1)
        for _ in range(2):
            self.assertEqual(
                self.post("assignments/remove", {"username": self.name}).status_code, 200
            )
        self.assertEqual(self.event_count(player.account_id, "AGENT_ASSIGNED"), 2)
        self.assertEqual(self.event_count(player.account_id, "AGENT_UNASSIGNED"), 2)

    def test_disable_revokes_session_replay_cannot_undo_later_enable(self):
        _, player = self.fixtures()
        with self.engine.begin() as connection:
            token = self.session(connection, player.account_id, "PLAYER")
        body = {"identifier": self.name, "enabled": False}
        key = str(uuid.uuid4())
        self.assertEqual(self.post("accounts/status", body, key).status_code, 200)
        with self.engine.connect() as connection:
            revoked = connection.scalar(
                select(AccountSession.revoked_at).where(
                    AccountSession.token_digest == session_token_digest(token)
                )
            )
            self.assertIsNotNone(revoked)
        self.assertEqual(self.post("accounts/status", {**body, "enabled": True}).status_code, 200)
        self.assertTrue(self.post("accounts/status", body, key).json()["replayed"])
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.scalar(select(Account.status).where(Account.id == player.account_id)),
                "ENABLED",
            )
        self.assertEqual(self.event_count(player.account_id, "ACCOUNT_DISABLED"), 1)

    def test_agent_player_unknown_and_stale_owner_denied_before_lookup(self):
        agent, player = self.fixtures()
        with self.engine.begin() as connection:
            tokens = [
                self.session(connection, agent.account_id, "AGENT"),
                self.session(connection, player.account_id, "PLAYER"),
                secrets.token_urlsafe(32),
            ]
            connection.execute(
                update(AccountSession.__table__)
                .where(AccountSession.token_digest == session_token_digest(self.token))
                .values(
                    issued_at=func.now() - text("interval '11 minutes'"),
                    mfa_verified_at=func.now() - text("interval '11 minutes'"),
                    absolute_expires_at=func.now() + text("interval '7 hours 49 minutes'"),
                )
            )
        for token in (*tokens, self.token):
            self.client.cookies.set(SESSION_COOKIE, token)
            for route, body in (
                ("agents", {}),
                ("players", {"username": self.name}),
                ("accounts/status", {"identifier": self.name, "enabled": False}),
                ("assignments", {"username": self.name, "agent_id": agent.login_id}),
                ("assignments/remove", {"username": self.name}),
            ):
                response = self.post(route, body)
                self.assertIn(response.status_code, (403, 429), response.text)

    def test_schema_rejects_unknown_fields_types_and_owner_target(self):
        for route, body in (
            ("agents", {"role": "OWNER"}),
            ("agents", {"agent_id": None}),
            ("players", {}),
            ("players", {"username": 42}),
            ("assignments", {"username": self.name}),
            ("accounts/status", {"identifier": self.name, "enabled": 0}),
            ("assignments/remove", {"username": self.name, "extra": True}),
        ):
            self.assertEqual(self.post(route, body).status_code, 400)
        for name in ("owner", "unknown_user"):
            self.assertEqual(
                self.post("accounts/status", {"identifier": name, "enabled": False}).status_code,
                403,
            )

    def test_missing_csrf_cross_origin_forwarding_and_malformed_envelopes(self):
        for headers in (
            {CSRF_HEADER: "wrong"},
            {"origin": "https://evil.example"},
            {"x-forwarded-for": "203.0.113.1"},
            {"idempotency-key": "bad"},
        ):
            self.assertIn(self.post("agents", {}, **headers).status_code, (401, 503))
        response = self.client.post(
            BASE + "players",
            content='{"username":"a","username":"b"}',
            headers=self.headers(**{"content-type": "application/json"}),
        )
        self.assertEqual(response.status_code, 401)

    def test_duplicate_identifiers_denied_and_failed_action_has_no_receipt(self):
        self.fixtures()
        key = str(uuid.uuid4())
        self.assertEqual(self.post("players", {"username": self.name}, key).status_code, 403)
        with self.engine.connect() as connection:
            self.assertIsNone(
                connection.scalar(
                    select(OperatorWriteReceipt.request_key).where(
                        OperatorWriteReceipt.owner_account_id == self.owner,
                        OperatorWriteReceipt.request_key == uuid.UUID(key),
                    )
                )
            )

    def test_attempts_throttle_and_denials_count(self):
        for _ in range(20):
            self.assertEqual(self.post("players", {"username": "owner"}).status_code, 403)
        response = self.post("agents", {})
        self.assertEqual(response.status_code, 429)
        self.assertGreater(int(response.headers["retry-after"]), 0)

    def test_concurrent_generated_agent_requests_commit_once(self):
        from concurrent.futures import ThreadPoolExecutor

        key = str(uuid.uuid4())

        def request_once(_):
            with TestClient(
                app,
                base_url=ORIGIN,
                client=("203.0.113.73", 50433),
                cookies={SESSION_COOKIE: self.token, CSRF_COOKIE: self.csrf},
            ) as client:
                return client.post(BASE + "agents", json={}, headers=self.headers(key))

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(request_once, range(2)))
        self.assertEqual(sorted(r.status_code for r in responses), [200, 201])
        self.assertEqual(len({r.json()["account_id"] for r in responses}), 1)
        self.assertEqual(sum("secret" in r.json() for r in responses), 1)
        target = uuid.UUID(responses[0].json()["account_id"])
        self.assertEqual(self.event_count(target, "INITIAL_CREDENTIAL_ISSUED"), 1)

    def test_revoked_owner_cannot_replay_and_receipts_are_immutable(self):
        key = str(uuid.uuid4())
        self.assertEqual(self.post("agents", {}, key).status_code, 201)
        with self.engine.begin() as connection:
            connection.execute(
                update(AccountSession.__table__)
                .where(AccountSession.token_digest == session_token_digest(self.token))
                .values(revoked_at=func.now())
            )
        self.assertEqual(self.post("agents", {}, key).status_code, 403)
        from sqlalchemy.exc import DatabaseError

        with self.assertRaises(DatabaseError), self.engine.begin() as connection:
            connection.execute(
                update(OperatorWriteReceipt.__table__)
                .where(
                    OperatorWriteReceipt.owner_account_id == self.owner,
                    OperatorWriteReceipt.request_key == uuid.UUID(key),
                )
                .values(request_digest="a" * 64)
            )
        with self.assertRaises(IntegrityError), self.engine.begin() as connection:
            connection.execute(
                insert(OperatorWriteReceipt.__table__).values(
                    owner_account_id=self.owner,
                    request_key=uuid.uuid4(),
                    request_digest="a" * 64,
                    response={"secret": "must never be persisted"},
                )
            )

    def test_receipt_insert_failure_rolls_back_created_account_and_audit(self):
        from fairmount_api.identity import operator_api

        original = operator_api.insert

        def fail_receipt(table):
            if table is OperatorWriteReceipt.__table__:
                raise IntegrityError("simulated receipt failure", {}, Exception())
            return original(table)

        with patch.object(operator_api, "insert", side_effect=fail_receipt):
            response = self.post("players", {"username": self.name})
        self.assertEqual(response.status_code, 503)
        # The same username can be provisioned: the whole failed action rolled back.
        self.assertEqual(self.post("players", {"username": self.name}).status_code, 201)
