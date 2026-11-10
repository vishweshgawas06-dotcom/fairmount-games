"""Committed owner HTTP lifecycle checks; run after rollback-isolated modules."""

import base64
import os
import secrets
import tempfile
import unittest
import uuid
from datetime import UTC
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
                    "accounts/setup-secret",
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
        if route in ("agents", "players"):
            body = {
                "display_name": "Test member",
                "mobile_number": "unverified shared contact",
                **body,
            }
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
                        OperatorWriteReceipt.actor_account_id == self.owner,
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
                ("accounts/setup-secret", {"identifier": self.name}),
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
                        OperatorWriteReceipt.actor_account_id == self.owner,
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
                return client.post(
                    BASE + "agents",
                    json={"display_name": "Test agent", "mobile_number": "unverified contact"},
                    headers=self.headers(key),
                )

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
                    OperatorWriteReceipt.actor_account_id == self.owner,
                    OperatorWriteReceipt.request_key == uuid.UUID(key),
                )
                .values(request_digest="a" * 64)
            )
        with self.assertRaises(IntegrityError), self.engine.begin() as connection:
            connection.execute(
                insert(OperatorWriteReceipt.__table__).values(
                    actor_account_id=self.owner,
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

    def activate(self, member, *, role="PLAYER", identifier=None, secret=None, password=None):
        return self.client.post(
            "/api/v1/auth/activate",
            json={
                "role": role,
                "identifier": identifier or member.login_id,
                "secret": secret if secret is not None else member.secret,
                "new_password": password if password is not None else "  सुरक्षित passphrase 42  ",
            },
            headers={"origin": ORIGIN},
        )

    def test_activation_for_both_roles_then_login_without_auto_session(self):
        agent, player = self.fixtures()
        for member, role in ((agent, "AGENT"), (player, "PLAYER")):
            response = self.activate(member, role=role)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), {"status": "activated"})
            self.assertNotIn("set-cookie", response.headers)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(self.event_count(member.account_id, "INITIAL_CREDENTIAL_CONSUMED"), 1)
            self.assertEqual(self.activate(member, role=role).status_code, 401)
            with self.engine.connect() as connection:
                credential = connection.execute(
                    select(AccountCredential).where(
                        AccountCredential.account_id == member.account_id
                    )
                ).one()
                self.assertIsNone(credential.initial_secret_digest)
                self.assertIsNone(credential.initial_secret_expires_at)
                self.assertIsNotNone(credential.initial_secret_consumed_at)
                self.assertIsNone(
                    connection.scalar(
                        select(AccountSession.id).where(
                            AccountSession.account_id == member.account_id
                        )
                    )
                )
            with TestClient(app, base_url=ORIGIN, client=("203.0.113.75", 50111)) as client:
                login = client.post(
                    "/api/v1/auth/login",
                    json={
                        "role": role,
                        "identifier": member.login_id,
                        "password": "  सुरक्षित passphrase 42  ",
                    },
                    headers={"origin": ORIGIN},
                )
                self.assertEqual(login.status_code, 200, login.text)
                self.assertIn("set-cookie", login.headers)

    def test_reissue_rotates_pending_secret_once_with_nonsecret_replay(self):
        _, member = self.fixtures()
        body = {"identifier": member.login_id}
        key = str(uuid.uuid4())
        response = self.post("accounts/setup-secret", body, key)
        self.assertEqual(response.status_code, 200, response.text)
        secret = response.json()["secret"]
        self.assertNotEqual(secret, member.secret)
        replay = self.post("accounts/setup-secret", body, key)
        self.assertTrue(replay.json()["replayed"])
        self.assertNotIn("secret", replay.json())
        self.assertEqual(self.event_count(member.account_id, "INITIAL_CREDENTIAL_REISSUED"), 1)
        self.assertEqual(self.activate(member).status_code, 401)
        self.assertEqual(self.activate(member, secret=secret).status_code, 200)
        self.assertEqual(self.post("accounts/setup-secret", body).status_code, 403)
        # An old receipt acknowledges delivery but must never rotate an active password.
        self.assertTrue(self.post("accounts/setup-secret", body, key).json()["replayed"])
        self.assertEqual(self.event_count(member.account_id, "INITIAL_CREDENTIAL_REISSUED"), 1)

    def test_activation_failures_and_throttling_are_generic_and_audited(self):
        from fairmount_api.db.models import AuthFailureEvent
        from fairmount_api.identity import activation_api
        from fairmount_api.identity.auth_attempts import _digests
        from fairmount_api.identity.auth_hmac_key import load_auth_hmac_key

        _, member = self.fixtures()
        for _ in range(5):
            self.assertEqual(self.activate(member, secret="wrong").status_code, 401)
        # A correct proof is not evaluated once the subject window is blocked.
        with patch.object(activation_api, "activate_member") as execute:
            self.assertEqual(self.activate(member).status_code, 401)
            execute.assert_not_called()
        digest, _ = _digests(
            "MEMBER_ACTIVATION", f"PLAYER:{self.name}", "203.0.113.73", load_auth_hmac_key()
        )
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(AuthFailureEvent).where(AuthFailureEvent.subject_digest == digest)
            ).all()
            self.assertEqual([r.outcome for r in rows].count("FAILED"), 5)
            self.assertEqual([r.outcome for r in rows].count("THROTTLED"), 1)
            self.assertNotIn(member.secret, str(rows))
            self.assertNotIn(self.name, str(rows))

    def test_activation_rejects_weak_wrong_role_missing_disabled_and_expired(self):
        agent, member = self.fixtures()
        self.assertEqual(self.activate(member, password="password1234").status_code, 401)
        self.assertEqual(self.activate(member, role="AGENT").status_code, 401)
        self.assertEqual(self.activate(member, identifier="not_present").status_code, 401)
        self.assertEqual(
            self.post(
                "accounts/status", {"identifier": agent.login_id, "enabled": False}
            ).status_code,
            200,
        )
        self.assertEqual(self.activate(agent, role="AGENT").status_code, 401)
        self.assertEqual(
            self.post("accounts/setup-secret", {"identifier": agent.login_id}).status_code, 403
        )
        with self.engine.begin() as connection:
            connection.execute(
                update(AccountCredential.__table__)
                .where(AccountCredential.account_id == member.account_id)
                .values(
                    initial_secret_issued_at=func.now() - text("interval '2 days'"),
                    initial_secret_expires_at=func.now() - text("interval '1 day'"),
                )
            )
        self.assertEqual(self.activate(member).status_code, 401)
        # An expired pending credential can be recovered by a freshly verified owner.
        rotated = self.post("accounts/setup-secret", {"identifier": self.name})
        self.assertEqual(rotated.status_code, 200)
        self.assertEqual(self.activate(member, secret=rotated.json()["secret"]).status_code, 200)

    def test_activation_request_schema_transport_and_no_owner_bypass(self):
        _, member = self.fixtures()
        body = {
            "role": "PLAYER",
            "identifier": self.name,
            "secret": member.secret,
            "new_password": "valid long passphrase",
        }
        for payload in (
            {**body, "role": "OWNER"},
            {**body, "extra": True},
            {**body, "secret": None},
            {**body, "new_password": "x" * 129},
            [],
        ):
            self.assertEqual(
                self.client.post(
                    "/api/v1/auth/activate", json=payload, headers={"origin": ORIGIN}
                ).status_code,
                400,
            )
        self.assertEqual(
            self.client.post(
                "/api/v1/auth/activate", json=body, headers={"origin": "https://evil.example"}
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/auth/activate",
                json=body,
                headers={"origin": ORIGIN, "x-forwarded-for": "203.0.113.7"},
            ).status_code,
            503,
        )
        duplicate = '{"role":"PLAYER","role":"OWNER"}'
        self.assertEqual(
            self.client.post(
                "/api/v1/auth/activate",
                content=duplicate,
                headers={"origin": ORIGIN, "content-type": "application/json"},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/auth/activate",
                json={**body, "new_password": "a" * 5000},
                headers={"origin": ORIGIN},
            ).status_code,
            400,
        )

    def test_concurrent_activation_consumes_secret_exactly_once(self):
        from concurrent.futures import ThreadPoolExecutor

        _, member = self.fixtures()
        body = {
            "role": "PLAYER",
            "identifier": self.name,
            "secret": member.secret,
            "new_password": "a strong member passphrase",
        }

        def attempt(_):
            with TestClient(app, base_url=ORIGIN, client=("203.0.113.76", 50112)) as client:
                return client.post("/api/v1/auth/activate", json=body, headers={"origin": ORIGIN})

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(attempt, range(2)))
        self.assertEqual(sorted(r.status_code for r in responses), [200, 401])
        self.assertEqual(self.event_count(member.account_id, "INITIAL_CREDENTIAL_CONSUMED"), 1)

    def test_activation_audit_failure_rolls_back_password_and_secret_consumption(self):
        from fairmount_api.identity import member_activation

        _, member = self.fixtures()
        with patch.object(
            member_activation,
            "insert",
            side_effect=IntegrityError("simulated audit failure", {}, Exception()),
        ):
            self.assertEqual(self.activate(member).status_code, 503)
        self.assertEqual(self.event_count(member.account_id, "INITIAL_CREDENTIAL_CONSUMED"), 0)
        self.assertEqual(self.activate(member).status_code, 200)

    def test_activation_rechecks_expiry_after_hashing(self):
        from fairmount_api.identity import member_activation

        _, member = self.fixtures()

        # Simulate a long hash operation crossing the expiry boundary without
        # depending on wall-clock sleeps or mutating immutable account state.
        def delayed_hash(_):
            # This runs in the request transaction/thread; changing the returned
            # clock values below models expiry during hashing deterministically.
            return "hash-not-to-be-stored"

        original = member_activation._pending_credential
        from datetime import datetime, timedelta
        from types import SimpleNamespace

        def expiring(connection, target):
            row = original(connection, target)
            return SimpleNamespace(
                initial_secret_digest=row.initial_secret_digest,
                initial_secret_expires_at=datetime.now(UTC) + timedelta(seconds=5),
            )

        # Make the second clock read beyond expiry; all actual DB statements
        # still execute, only the SQL function expression used here is offset.
        with (
            patch.object(member_activation, "_pending_credential", side_effect=expiring),
            patch.object(member_activation, "hash_password", side_effect=delayed_hash),
            patch.object(member_activation, "func") as clock,
        ):
            clock.clock_timestamp.side_effect = [
                func.clock_timestamp(),
                func.clock_timestamp() + text("interval '10 seconds'"),
            ]
            self.assertEqual(self.activate(member).status_code, 401)
        self.assertEqual(self.activate(member).status_code, 200)

    def test_activation_reissue_race_has_one_consistent_credential_state(self):
        from concurrent.futures import ThreadPoolExecutor

        _, member = self.fixtures()

        def attempt(which):
            with TestClient(
                app,
                base_url=ORIGIN,
                client=("203.0.113.77", 50119),
                cookies={SESSION_COOKIE: self.token, CSRF_COOKIE: self.csrf},
            ) as client:
                if which == "activate":
                    return client.post(
                        "/api/v1/auth/activate",
                        json={
                            "role": "PLAYER",
                            "identifier": self.name,
                            "secret": member.secret,
                            "new_password": "a strong permanent passphrase",
                        },
                        headers={"origin": ORIGIN},
                    )
                return client.post(
                    BASE + "accounts/setup-secret",
                    json={"identifier": self.name},
                    headers=self.headers(),
                )

        with ThreadPoolExecutor(max_workers=2) as pool:
            activation, rotation = list(pool.map(attempt, ("activate", "rotate")))
        self.assertIn((activation.status_code, rotation.status_code), ((200, 403), (401, 200)))
        if rotation.status_code == 200:
            self.assertEqual(
                self.activate(member, secret=rotation.json()["secret"]).status_code, 200
            )
        self.assertEqual(self.event_count(member.account_id, "INITIAL_CREDENTIAL_CONSUMED"), 1)

    def test_nonencodable_secret_is_a_generic_proof_denial_not_server_error(self):
        _, member = self.fixtures()
        import json

        raw = json.dumps(
            {
                "role": "PLAYER",
                "identifier": self.name,
                "secret": "\ud800",
                "new_password": "a valid permanent passphrase",
            }
        )
        response = self.client.post(
            "/api/v1/auth/activate",
            content=raw,
            headers={"origin": ORIGIN, "content-type": "application/json"},
        )
        self.assertEqual(response.status_code, 401)
        malformed_identifier = json.dumps(
            {
                "role": "PLAYER",
                "identifier": "\ud800",
                "secret": member.secret,
                "new_password": "a valid permanent passphrase",
            }
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/auth/activate",
                content=malformed_identifier,
                headers={"origin": ORIGIN, "content-type": "application/json"},
            ).status_code,
            401,
        )
        self.assertEqual(self.activate(member).status_code, 200)

    def agent_browser(self, agent, source="203.0.113.81"):
        self.assertEqual(self.activate(agent, role="AGENT").status_code, 200)
        client = TestClient(app, base_url=ORIGIN, client=(source, 51000))
        self.addCleanup(client.close)
        login = client.post(
            "/api/v1/auth/login",
            headers={"origin": ORIGIN},
            json={
                "role": "AGENT",
                "identifier": agent.login_id,
                "password": "  सुरक्षित passphrase 42  ",
            },
        )
        self.assertEqual(login.status_code, 200, login.text)
        return client

    def agent_post(self, client, body, key=None):
        return client.post(
            "/api/v1/agent/players",
            json=body,
            headers={
                "origin": ORIGIN,
                CSRF_HEADER: client.cookies.get(CSRF_COOKIE),
                "idempotency-key": key or str(uuid.uuid4()),
            },
        )

    def profile_body(self, suffix="new"):
        return {
            "username": self.name + "_" + suffix,
            "display_name": "  खिलाड़ी Test  ",
            "mobile_number": "unverified shared contact",
        }

    def test_agent_real_login_creates_only_own_assigned_zero_balance_player(self):
        from fairmount_api.db.models import AccountWallet, PrivateIdentity

        agent, _ = self.fixtures()
        browser = self.agent_browser(agent)
        body = self.profile_body()
        key = str(uuid.uuid4())
        response = self.agent_post(browser, body, key)
        self.assertEqual(response.status_code, 201, response.text)
        payload = response.json()
        target = uuid.UUID(payload["account_id"])
        replay = self.agent_post(browser, body, key)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json()["account_id"], payload["account_id"])
        self.assertNotIn("secret", replay.json())
        self.assertTrue(replay.json()["replayed"])
        with self.engine.connect() as connection:
            row = connection.execute(
                select(AgentAssignment).where(AgentAssignment.player_account_id == target)
            ).one()
            self.assertEqual(
                (row.agent_account_id, row.actor_account_id), (agent.account_id, agent.account_id)
            )
            profile = connection.execute(
                select(PrivateIdentity).where(PrivateIdentity.account_id == target)
            ).one()
            self.assertEqual(profile.display_name, body["display_name"])
            self.assertEqual(profile.mobile_number, body["mobile_number"])
            self.assertEqual(
                connection.scalar(
                    select(AccountWallet.balance).where(AccountWallet.account_id == target)
                ),
                0,
            )
            receipt = connection.scalar(
                select(OperatorWriteReceipt.response).where(
                    OperatorWriteReceipt.actor_account_id == agent.account_id,
                    OperatorWriteReceipt.request_key == uuid.UUID(key),
                )
            )
            self.assertNotIn(payload["secret"], str(receipt))
            events = connection.execute(
                select(SecurityEvent.actor_account_id).where(
                    SecurityEvent.target_account_id == target
                )
            ).all()
            self.assertEqual(events, [(agent.account_id,), (agent.account_id,)])
        own = browser.get(f"/api/v1/players/{target}/wallet", headers={"origin": ORIGIN})
        self.assertEqual(own.status_code, 200, own.text)
        self.assertNotIn(body["display_name"], own.text)

    def test_profile_fields_are_required_bounded_private_and_shared_contact_allowed(self):
        from fairmount_api.db.models import PrivateIdentity

        for route, base in (("agents", {}), ("players", {"username": self.name})):
            response = self.client.post(BASE + route, json=base, headers=self.headers())
            self.assertEqual(response.status_code, 400)
        for field, value in (
            ("display_name", " "),
            ("mobile_number", ""),
            ("display_name", "x" * 161),
            ("mobile_number", "x" * 33),
            ("display_name", "line\nbreak"),
            ("mobile_number", 42),
        ):
            body = {**self.profile_body(), field: value}
            self.assertEqual(self.post("players", body).status_code, 400)
        for suffix in ("one", "two"):
            body = self.profile_body(suffix)
            response = self.post("players", body)
            self.assertEqual(response.status_code, 201, response.text)
            self.assertNotIn(body["mobile_number"], response.text)
            with self.engine.connect() as connection:
                self.assertEqual(
                    connection.scalar(
                        select(PrivateIdentity.mobile_number).where(
                            PrivateIdentity.account_id == uuid.UUID(response.json()["account_id"])
                        )
                    ),
                    body["mobile_number"],
                )

    def test_agent_cannot_select_another_agent_create_subagent_or_reissue(self):
        agent, _ = self.fixtures()
        browser = self.agent_browser(agent)
        for extra in (
            {"agent_id": agent.login_id},
            {"role": "AGENT"},
            {"account_id": str(self.owner)},
            {"balance": 100},
            {"owner_managed": True},
        ):
            self.assertEqual(
                self.agent_post(browser, {**self.profile_body(), **extra}).status_code, 400
            )
        for route, body in (
            ("agents", {"display_name": "Subagent", "mobile_number": "contact"}),
            ("accounts/setup-secret", {"identifier": self.name}),
        ):
            response = browser.post(
                BASE + route,
                json=body,
                headers={
                    "origin": ORIGIN,
                    CSRF_HEADER: browser.cookies.get(CSRF_COOKIE),
                    "idempotency-key": str(uuid.uuid4()),
                },
            )
            self.assertEqual(response.status_code, 403)
        # Even an owner cannot use an agent-only endpoint under a forged role.
        self.assertEqual(self.agent_post(self.client, self.profile_body()).status_code, 403)

    def test_agent_registration_disabled_and_revoked_sessions_denied(self):
        agent, _ = self.fixtures()
        browser = self.agent_browser(agent)
        key = str(uuid.uuid4())
        self.assertEqual(self.agent_post(browser, self.profile_body(), key).status_code, 201)
        self.assertEqual(
            self.post(
                "accounts/status", {"identifier": agent.login_id, "enabled": False}
            ).status_code,
            200,
        )
        self.assertEqual(self.agent_post(browser, self.profile_body(), key).status_code, 403)
        self.assertEqual(self.agent_post(browser, self.profile_body("next")).status_code, 403)

    def test_two_agents_race_on_one_global_username_with_no_orphan_accounts(self):
        from concurrent.futures import ThreadPoolExecutor

        from fairmount_api.db.models import PrivateIdentity

        first, _ = self.fixtures()
        with self.engine.begin() as connection:
            second = provision_agent(connection, self.token)
        browsers = [self.agent_browser(first), self.agent_browser(second, "203.0.113.82")]
        body = self.profile_body("race")
        with self.engine.connect() as connection:
            before = connection.scalar(select(func.count()).select_from(Account))

        from threading import Barrier

        from fairmount_api.identity import agent_provisioning

        original_lookup = agent_provisioning._login_taken
        barrier = Barrier(2)

        def simultaneous_lookup(connection, role, canonical):
            exists = original_lookup(connection, role, canonical)
            barrier.wait(timeout=10)
            return exists

        # Distinct source/session windows and a barrier after the uniqueness
        # lookup force both transactions to attempt the same global identifier.
        with patch.object(agent_provisioning, "_login_taken", side_effect=simultaneous_lookup):
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(lambda browser: self.agent_post(browser, body), browsers))
        self.assertEqual(sorted(r.status_code for r in responses), [201, 403])
        winner = next(r for r in responses if r.status_code == 201)
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.scalar(select(func.count()).select_from(Account)), before + 1
            )
            self.assertEqual(
                connection.scalar(
                    select(func.count())
                    .select_from(PrivateIdentity)
                    .where(PrivateIdentity.login_identifier == body["username"])
                ),
                1,
            )
        # The losing agent cannot inspect the newly created player's wallet.
        loser = browsers[0] if responses[0].status_code == 403 else browsers[1]
        self.assertNotEqual(
            loser.get(
                f"/api/v1/players/{winner.json()['account_id']}/wallet", headers={"origin": ORIGIN}
            ).status_code,
            200,
        )

    def test_agent_assignment_audit_failure_rolls_back_entire_registration(self):
        from fairmount_api.db.models import PrivateIdentity
        from fairmount_api.identity import agent_provisioning

        agent, _ = self.fixtures()
        browser = self.agent_browser(agent)
        body = self.profile_body()
        with patch.object(
            agent_provisioning,
            "insert",
            side_effect=IntegrityError("simulated assignment failure", {}, Exception()),
        ):
            self.assertEqual(self.agent_post(browser, body).status_code, 503)
        with self.engine.connect() as connection:
            self.assertIsNone(
                connection.scalar(
                    select(PrivateIdentity.account_id).where(
                        PrivateIdentity.login_identifier == body["username"]
                    )
                )
            )
        self.assertEqual(self.agent_post(browser, body).status_code, 201)

    def test_agent_request_key_is_bound_to_actor_and_body(self):
        first, _ = self.fixtures()
        with self.engine.begin() as connection:
            second = provision_agent(connection, self.token)
        first_browser, second_browser = self.agent_browser(first), self.agent_browser(second)
        key = str(uuid.uuid4())
        one = self.agent_post(first_browser, self.profile_body("first"), key)
        two = self.agent_post(second_browser, self.profile_body("second"), key)
        self.assertEqual((one.status_code, two.status_code), (201, 201))
        self.assertNotEqual(one.json()["account_id"], two.json()["account_id"])
        self.assertEqual(
            self.agent_post(first_browser, self.profile_body("changed"), key).status_code, 409
        )

    def balance(self, account):
        from fairmount_api.db.models import AccountWallet

        with self.engine.connect() as connection:
            return connection.scalar(
                select(AccountWallet.balance).where(AccountWallet.account_id == account)
            )

    def reserve_balance(self):
        from fairmount_api.db.models import GameReserve

        with self.engine.connect() as connection:
            return connection.scalar(select(GameReserve.balance).where(GameReserve.id == 1))

    def agent_transfer(self, browser, username, amount, *, to_player=True, key=None):
        return browser.post(
            "/api/v1/agent/points/transfer",
            json={
                "username": username,
                "amount": amount,
                "to_player": to_player,
                "reason": "requested allocation or return",
            },
            headers={
                "origin": ORIGIN,
                CSRF_HEADER: browser.cookies.get(CSRF_COOKIE),
                "idempotency-key": key or str(uuid.uuid4()),
            },
        )

    def test_owner_issuance_replays_once_with_exact_ledger_actor_reason(self):
        from fairmount_api.db.models import PointOperation

        before = self.balance(self.owner)
        key = str(uuid.uuid4())
        body = {"amount": 120, "reason": "audited virtual-points issuance"}
        first = self.post("points/issue", body, key)
        second = self.post("points/issue", body, key)
        self.assertEqual((first.status_code, second.status_code), (200, 200))
        self.assertEqual(first.json()["operation_id"], second.json()["operation_id"])
        self.assertTrue(second.json()["replayed"])
        self.assertEqual(self.balance(self.owner), before + 120)
        with self.engine.connect() as connection:
            operation = connection.execute(
                select(PointOperation).where(
                    PointOperation.id == uuid.UUID(first.json()["operation_id"])
                )
            ).one()
            self.assertEqual(operation.actor_account_id, self.owner)
            self.assertEqual(operation.kind, "OWNER_ISSUE")
            self.assertEqual(operation.amount, 120)
            self.assertEqual(operation.reason, body["reason"])
        self.assertEqual(self.post("points/issue", {**body, "amount": 121}, key).status_code, 409)

    def test_http_owner_agent_player_transfers_conserve_full_requested_amounts(self):
        agent, _ = self.fixtures()
        browser = self.agent_browser(agent)
        body = self.profile_body()
        created = self.agent_post(browser, body)
        player = uuid.UUID(created.json()["account_id"])
        before = self.balance(self.owner)
        self.assertEqual(
            self.post("points/issue", {"amount": 1000, "reason": "seed"}).status_code, 200
        )
        self.assertEqual(
            self.post(
                "points/transfer",
                {
                    "identifier": agent.login_id,
                    "amount": 100,
                    "to_member": True,
                    "reason": "agent allocation",
                },
            ).status_code,
            200,
        )
        self.assertEqual(self.agent_transfer(browser, body["username"], 60).status_code, 200)
        self.assertEqual(
            self.agent_transfer(browser, body["username"], 20, to_player=False).status_code, 200
        )
        self.assertEqual(
            self.post(
                "points/transfer",
                {
                    "identifier": body["username"],
                    "amount": 10,
                    "to_member": False,
                    "reason": "requested owner return",
                },
            ).status_code,
            200,
        )
        self.assertEqual(
            (
                self.balance(self.owner) - before,
                self.balance(agent.account_id),
                self.balance(player),
            ),
            (910, 60, 30),
        )
        self.assertEqual(
            self.balance(self.owner)
            - before
            + self.balance(agent.account_id)
            + self.balance(player),
            1000,
        )

    def test_http_transfers_reject_insufficient_disabled_and_stale_assignment_in_full(self):
        agent, player = self.fixtures()
        browser = self.agent_browser(agent)
        self.assertEqual(
            self.post(
                "assignments", {"username": self.name, "agent_id": agent.login_id}
            ).status_code,
            200,
        )
        self.assertEqual(self.agent_transfer(browser, self.name, 1).status_code, 403)
        self.assertEqual((self.balance(agent.account_id), self.balance(player.account_id)), (0, 0))
        self.assertEqual(
            self.post("points/issue", {"amount": 100, "reason": "seed"}).status_code, 200
        )
        self.assertEqual(
            self.post(
                "points/transfer",
                {"identifier": agent.login_id, "amount": 10, "to_member": True, "reason": "budget"},
            ).status_code,
            200,
        )
        self.assertEqual(self.agent_transfer(browser, self.name, 11).status_code, 403)
        self.assertEqual(self.agent_transfer(browser, self.name, 5).status_code, 200)
        self.assertEqual(self.post("assignments/remove", {"username": self.name}).status_code, 200)
        self.assertEqual(
            self.agent_transfer(browser, self.name, 1, to_player=False).status_code, 403
        )
        self.assertEqual(
            self.post("accounts/status", {"identifier": self.name, "enabled": False}).status_code,
            200,
        )
        self.assertEqual(
            self.post(
                "points/transfer",
                {
                    "identifier": self.name,
                    "amount": 1,
                    "to_member": False,
                    "reason": "must stay frozen",
                },
            ).status_code,
            403,
        )
        self.assertEqual((self.balance(agent.account_id), self.balance(player.account_id)), (5, 5))

    def test_point_write_schemas_and_agent_cannot_issue_or_manage_reserve(self):
        agent, _ = self.fixtures()
        browser = self.agent_browser(agent)
        for route in ("points/issue", "reserve/fund", "reserve/withdraw"):
            response = browser.post(
                BASE + route,
                json={"amount": 1, "reason": "denied"},
                headers={
                    "origin": ORIGIN,
                    CSRF_HEADER: browser.cookies.get(CSRF_COOKIE),
                    "idempotency-key": str(uuid.uuid4()),
                },
            )
            self.assertEqual(response.status_code, 403)
        for body in (
            {"amount": True, "reason": "bad"},
            {"amount": 0, "reason": "bad"},
            {"amount": 2**63, "reason": "bad"},
            {"amount": 1, "reason": " "},
            {"amount": 1},
            {"amount": 1, "reason": "x" * 501},
            {"amount": 1, "reason": "bad", "target": str(agent.account_id)},
        ):
            self.assertEqual(self.post("points/issue", body).status_code, 400)
        self.assertEqual(
            self.post(
                "points/transfer",
                {
                    "identifier": agent.login_id,
                    "amount": 1,
                    "to_member": "false",
                    "reason": "bad flag",
                },
            ).status_code,
            400,
        )
        with self.engine.begin() as connection:
            connection.execute(
                update(AccountSession.__table__)
                .where(AccountSession.token_digest == session_token_digest(self.token))
                .values(
                    issued_at=func.now() - text("interval '11 minutes'"),
                    mfa_verified_at=func.now() - text("interval '11 minutes'"),
                    absolute_expires_at=func.now() + text("interval '7 hours 49 minutes'"),
                )
            )
        self.assertEqual(
            self.post("points/issue", {"amount": 1, "reason": "stale MFA"}).status_code, 403
        )

    def test_http_reserve_funding_and_surplus_return_conserve_owner_points(self):
        before_owner, before_reserve = self.balance(self.owner), self.reserve_balance()
        self.assertEqual(
            self.post("points/issue", {"amount": 200, "reason": "seed"}).status_code, 200
        )
        key = str(uuid.uuid4())
        body = {"amount": 100, "reason": "separate game reserve"}
        response = self.post("reserve/fund", body, key)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(self.post("reserve/fund", body, key).json()["replayed"])
        self.assertEqual(
            self.post("reserve/withdraw", {"amount": 40, "reason": "proven surplus"}).status_code,
            200,
        )
        self.assertEqual(
            (self.balance(self.owner) - before_owner, self.reserve_balance() - before_reserve),
            (140, 60),
        )
        self.assertEqual(
            self.post(
                "reserve/withdraw",
                {"amount": self.reserve_balance() + 1, "reason": "unaffordable request"},
            ).status_code,
            403,
        )

    def test_http_concurrent_same_key_transfer_debits_once(self):
        from concurrent.futures import ThreadPoolExecutor

        _, member = self.fixtures()
        self.assertEqual(
            self.post("points/issue", {"amount": 100, "reason": "seed"}).status_code, 200
        )
        before = self.balance(self.owner)
        key = str(uuid.uuid4())
        body = {"identifier": self.name, "amount": 25, "to_member": True, "reason": "allocation"}

        def request_once(_):
            with TestClient(
                app,
                base_url=ORIGIN,
                client=("203.0.113.85", 51500),
                cookies={SESSION_COOKIE: self.token, CSRF_COOKIE: self.csrf},
            ) as client:
                return client.post(BASE + "points/transfer", json=body, headers=self.headers(key))

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(request_once, range(2)))
        self.assertEqual([r.status_code for r in responses], [200, 200])
        self.assertEqual(sum(r.json()["replayed"] for r in responses), 1)
        self.assertEqual(len({r.json()["operation_id"] for r in responses}), 1)
        self.assertEqual(
            (before - self.balance(self.owner), self.balance(member.account_id)), (25, 25)
        )

    def test_point_receipt_failure_rolls_back_ledger_and_projection(self):
        from fairmount_api.db.models import PointOperation
        from fairmount_api.identity import operator_api

        original = operator_api.insert

        def fail_receipt(table):
            if table is OperatorWriteReceipt.__table__:
                raise IntegrityError("receipt failed", {}, Exception())
            return original(table)

        before = self.balance(self.owner)
        key = str(uuid.uuid4())
        body = {"amount": 10, "reason": "must roll back together"}
        with patch.object(operator_api, "insert", side_effect=fail_receipt):
            self.assertEqual(self.post("points/issue", body, key).status_code, 503)
        self.assertEqual(self.balance(self.owner), before)
        with self.engine.connect() as connection:
            self.assertIsNone(
                connection.scalar(
                    select(PointOperation.id).where(
                        PointOperation.actor_account_id == self.owner,
                        PointOperation.idempotency_key == "http:" + key,
                    )
                )
            )
        self.assertEqual(self.post("points/issue", body, key).status_code, 200)
        self.assertEqual(self.balance(self.owner), before + 10)

    def test_http_withdrawal_cannot_remove_accepted_payout_or_refund_cover(self):
        from fairmount_api.db.models import RouletteBet, RouletteRound
        from fairmount_api.roulette.admission import place_bet
        from fairmount_api.roulette.round_clock import open_round

        _, player = self.fixtures()
        self.assertEqual(
            self.post("points/issue", {"amount": 1000, "reason": "seed"}).status_code, 200
        )
        self.assertEqual(
            self.post(
                "points/transfer",
                {
                    "identifier": self.name,
                    "amount": 100,
                    "to_member": True,
                    "reason": "player budget",
                },
            ).status_code,
            200,
        )
        self.assertEqual(
            self.post("reserve/fund", {"amount": 340, "reason": "winner coverage"}).status_code, 200
        )
        with self.engine.begin() as connection:
            token = self.session(connection, player.account_id, "PLAYER")
            round_id = connection.scalar(
                select(RouletteRound.id).where(RouletteRound.state == "OPEN")
            ) or open_round(connection)
            place_bet(
                connection,
                token,
                round_id=round_id,
                selection_key="straight:17",
                requested=10,
                idempotency_key="accepted-" + str(uuid.uuid4()),
            )
        reserve, owner = self.reserve_balance(), self.balance(self.owner)
        response = self.post(
            "reserve/withdraw", {"amount": reserve, "reason": "must preserve every accepted claim"}
        )
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual((self.reserve_balance(), self.balance(self.owner)), (reserve, owner))
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.scalar(
                    select(RouletteBet.accepted_stake).where(
                        RouletteBet.round_id == round_id,
                        RouletteBet.player_account_id == player.account_id,
                    )
                ),
                10,
            )

    def test_console_owner_context_roster_is_private_and_bounded(self):
        from fairmount_api.console_reads import PAGE_SIZE
        from fairmount_api.db.models import PrivateIdentity

        agent, member = self.fixtures()
        with self.engine.begin() as connection:
            connection.execute(
                update(PrivateIdentity.__table__)
                .where(PrivateIdentity.account_id == member.account_id)
                .values(display_name="Roster member", mobile_number="PRIVATE CONTACT")
            )
        context = self.client.get("/api/v1/console/context", headers={"origin": ORIGIN})
        self.assertEqual(context.status_code, 200, context.text)
        self.assertEqual(context.json()["role"], "OWNER")
        self.assertIsInstance(context.json()["balance"], str)
        self.assertIn("reserve_balance", context.json())
        self.assertEqual(context.headers["cache-control"], "no-store")
        # There can be earlier committed fixtures; consume bounded keyset pages.
        seen, cursor = [], None
        for _ in range(20):
            response = self.client.get(
                "/api/v1/console/members",
                params={"after": cursor} if cursor else {},
                headers={"origin": ORIGIN},
            )
            self.assertEqual(response.status_code, 200, response.text)
            page = response.json()
            self.assertLessEqual(len(page["items"]), PAGE_SIZE)
            self.assertNotIn("PRIVATE CONTACT", response.text)
            self.assertNotIn("initial_secret", response.text)
            seen.extend(row["account_id"] for row in page["items"])
            cursor = page["next_after"]
            if cursor is None:
                break
        self.assertIn(str(agent.account_id), seen)
        self.assertIn(str(member.account_id), seen)
        self.assertEqual(len(set(seen)), len(seen))

    def test_console_agent_roster_and_history_reauthorize_assignment(self):
        agent, member = self.fixtures()
        browser = self.agent_browser(agent)
        body = {"username": self.name, "agent_id": agent.login_id}
        self.assertEqual(self.post("assignments", body).status_code, 200)
        self.assertEqual(
            self.post("points/issue", {"amount": 100, "reason": "seed"}).status_code, 200
        )
        self.assertEqual(
            self.post(
                "points/transfer",
                {"identifier": agent.login_id, "amount": 50, "to_member": True, "reason": "budget"},
            ).status_code,
            200,
        )
        response = self.agent_transfer(browser, self.name, 10)
        operation = response.json()["operation_id"]
        context = browser.get("/api/v1/console/context").json()
        self.assertEqual(context["role"], "AGENT")
        self.assertNotIn("reserve_balance", context)
        roster = browser.get("/api/v1/console/members").json()["items"]
        self.assertEqual([row["account_id"] for row in roster], [str(member.account_id)])
        history = browser.get("/api/v1/console/history").json()["items"]
        self.assertEqual([row["operation_id"] for row in history], [operation])
        # Disabling a current player removes it and its transfer history from
        # this agent's current-scope projection, not just a browser-side filter.
        self.assertEqual(
            self.post("accounts/status", {"identifier": self.name, "enabled": False}).status_code,
            200,
        )
        self.assertEqual(browser.get("/api/v1/console/members").json()["items"], [])
        self.assertEqual(browser.get("/api/v1/console/history").json()["items"], [])
        self.assertEqual(
            self.post("accounts/status", {"identifier": self.name, "enabled": True}).status_code,
            200,
        )
        self.assertEqual(self.post("assignments/remove", {"username": self.name}).status_code, 200)
        self.assertEqual(browser.get("/api/v1/console/members").json()["items"], [])
        self.assertEqual(browser.get("/api/v1/console/history").json()["items"], [])

    def test_console_player_revoked_and_malformed_cursor_denials(self):
        _, member = self.fixtures()
        with self.engine.begin() as connection:
            player_token = self.session(connection, member.account_id, "PLAYER")
        with TestClient(
            app,
            base_url=ORIGIN,
            client=("203.0.113.91", 51020),
            cookies={SESSION_COOKIE: player_token},
        ) as client:
            for suffix in ("context", "members", "history"):
                self.assertEqual(client.get("/api/v1/console/" + suffix).status_code, 401)
        for route, query in (
            ("members", "after=bad"),
            ("history", "after=bad"),
            ("context", "account_id=bad"),
            ("history", "after=a&after=b"),
        ):
            self.assertEqual(
                self.client.get("/api/v1/console/" + route + "?" + query).status_code, 400
            )
        self.assertEqual(
            self.client.get(
                "/api/v1/console/context", headers={"x-forwarded-for": "203.0.113.1"}
            ).status_code,
            503,
        )
        with self.engine.begin() as connection:
            connection.execute(
                update(AccountSession.__table__)
                .where(AccountSession.token_digest == session_token_digest(self.token))
                .values(revoked_at=func.now())
            )
        for suffix in ("context", "members", "history"):
            self.assertEqual(self.client.get("/api/v1/console/" + suffix).status_code, 401)

    def test_console_history_is_administrative_not_gameplay_profit_or_loss(self):
        from fairmount_api.console_reads import ADMIN_KINDS, PAGE_SIZE

        self.assertEqual(
            self.post("points/issue", {"amount": 20, "reason": "console audit"}).status_code, 200
        )
        response = self.client.get("/api/v1/console/history")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertLessEqual(len(response.json()["items"]), PAGE_SIZE)
        self.assertTrue(response.json()["items"])
        for row in response.json()["items"]:
            self.assertIn(row["kind"], ADMIN_KINDS)
            self.assertIsInstance(row["amount"], str)
            for forbidden in ("idempotency_key", "request_fingerprint", "password", "context_id"):
                self.assertNotIn(forbidden, row)

    def test_console_history_cursor_preserves_timestamp_ties_without_duplicates(self):
        from fairmount_api import console_reads
        from fairmount_api.console_reads import decode_cursor
        from fairmount_api.point_accounting import issue_owner_points

        expected = set()
        with self.engine.begin() as connection:
            for _ in range(7):
                operation = issue_owner_points(
                    connection,
                    self.token,
                    amount=1,
                    reason="timestamp tie pagination",
                    idempotency_key=str(uuid.uuid4()),
                )
                expected.add(str(operation.operation_id))
        seen, cursor = [], None
        with patch.object(console_reads, "PAGE_SIZE", 3):
            for _ in range(10):
                response = self.client.get(
                    "/api/v1/console/history", params={"after": cursor} if cursor else {}
                )
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertLessEqual(len(payload["items"]), 3)
                seen.extend(row["operation_id"] for row in payload["items"])
                cursor = payload["next_after"]
                if cursor:
                    decode_cursor(cursor)
                if expected <= set(seen):
                    break
                if cursor is None:
                    break
        self.assertTrue(expected <= set(seen))
        self.assertEqual(len(seen), len(set(seen)))
