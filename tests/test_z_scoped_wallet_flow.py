"""Committed agent HTTP resource scope against disposable migrated PostgreSQL.

This fixture seeds already issued test sessions and assignments; it is NOT an
agent registration/login test. Immutable wallet rows require disposable CI DB.
"""

import os
import secrets
import unittest
from types import MappingProxyType
from unittest.mock import patch

from fairmount_api.db.models import Account, AccountSession, AgentAssignment, OwnerRecoveryCode
from fairmount_api.identity.http_boundary import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE
from fairmount_api.identity.mfa import totp_code
from fairmount_api.identity.mfa_keys import MFAKeyring
from fairmount_api.identity.owner_activation import activate_initial_owner
from fairmount_api.identity.owner_bootstrap import bootstrap_owner
from fairmount_api.identity.owner_mfa_enrollment import (
    begin_owner_mfa_enrollment,
    confirm_owner_mfa_enrollment,
)
from fairmount_api.identity.session_validation import session_token_digest
from fairmount_api.main import app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, insert, select, text, update

from infrastructure.local_db_url import local_database_url

ORIGIN = "https://game.example"


def player_url(player):
    return f"/api/v1/players/{player}/wallet"


CONFIG = {"FAIRMOUNT_AUTH_EDGE_MODE": "direct-tls", "FAIRMOUNT_PUBLIC_ORIGIN": ORIGIN}


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "Disposable PostgreSQL test DB required"
)
class ScopedWalletHTTPFlowTests(unittest.TestCase):
    def test_owner_password_mfa_http_flow_and_disabled_claim_audit(self):
        engine = create_engine(local_database_url(test=True))
        password = "long private owner test passphrase"
        keyring = MFAKeyring(1, MappingProxyType({1: secrets.token_bytes(32)}))
        try:
            # Commit real internal bootstrap, activation and ten-code MFA setup.
            # No owner secret/key is written to disk or returned by HTTP.
            with engine.begin() as connection:
                pending_owner = bootstrap_owner(connection)
                owner = activate_initial_owner(connection, pending_owner.secret, password)
                pending_mfa = begin_owner_mfa_enrollment(connection, keyring)
                now = connection.scalar(select(func.clock_timestamp()))
                confirmed = confirm_owner_mfa_enrollment(
                    connection,
                    totp_code(pending_mfa.secret, int(now.timestamp())),
                    keyring,
                )
                code = confirmed.recovery_codes[0]
                enabled = connection.execute(
                    insert(Account.__table__).values(role="PLAYER").returning(Account.id)
                ).scalar_one()
                disabled = connection.execute(
                    insert(Account.__table__).values(role="PLAYER").returning(Account.id)
                ).scalar_one()
                connection.execute(
                    update(Account.__table__)
                    .where(Account.id == disabled)
                    .values(status="DISABLED", disabled_at=func.now())
                )
            client = TestClient(app, base_url=ORIGIN, client=("203.0.113.43", 50003))
            with (
                patch.dict("os.environ", CONFIG),
                patch("fairmount_api.identity.login_api._configured_engine", return_value=engine),
                patch("fairmount_api.private_read_api._configured_engine", return_value=engine),
                patch(
                    "fairmount_api.identity.login_api.load_auth_hmac_key",
                    return_value=b"separate-test-owner-hmac-secret!",
                ),
                patch("fairmount_api.identity.login_api.load_mfa_keyring", return_value=keyring),
            ):
                payload = {
                    "role": "OWNER",
                    "identifier": "owner",
                    "password": password,
                    "factor_kind": "recovery",
                    "code": code,
                }
                logged_in = client.post(
                    "/api/v1/auth/login", json=payload, headers={"Origin": ORIGIN}
                )
                self.assertEqual(
                    (logged_in.status_code, logged_in.json()), (200, {"status": "authenticated"})
                )
                token, csrf = client.cookies[SESSION_COOKIE], client.cookies[CSRF_COOKIE]
                self.assertNotIn(token, logged_in.text)
                self.assertNotIn(code, logged_in.text)
                with engine.connect() as connection:
                    self.assertIsNotNone(
                        connection.scalar(
                            select(OwnerRecoveryCode.consumed_at).where(
                                OwnerRecoveryCode.owner_account_id == owner,
                                OwnerRecoveryCode.digest.is_not(None),
                                OwnerRecoveryCode.consumed_at.is_not(None),
                            )
                        )
                    )
                for player in (enabled, disabled):
                    response = client.get(player_url(player))
                    self.assertEqual(
                        (response.status_code, response.json()),
                        (200, {"account_id": str(player), "balance": 0}),
                    )
                roster = client.get("/api/v1/me/players")
                self.assertEqual(roster.status_code, 200)
                self.assertIn(str(enabled), roster.json()["player_ids"])
                self.assertNotIn(str(disabled), roster.json()["player_ids"])
                self.assertNotIn(str(owner), roster.json()["player_ids"])
                logout = client.post(
                    "/api/v1/auth/logout",
                    headers={"Origin": ORIGIN, CSRF_HEADER: csrf},
                )
                self.assertEqual(logout.status_code, 200)
                stale = TestClient(app, base_url=ORIGIN, client=("203.0.113.43", 50004))
                stale.cookies.set(SESSION_COOKIE, token, domain="game.example")
                self.assertEqual(stale.get("/api/v1/me/players").status_code, 401)
                self.assertEqual(stale.get(player_url(disabled)).status_code, 404)
                replay = client.post("/api/v1/auth/login", json=payload, headers={"Origin": ORIGIN})
                self.assertEqual(replay.status_code, 401)
                self.assertNotIn("set-cookie", replay.headers)
        finally:
            engine.dispose()

    def test_reassign_and_disable_revoke_agent_http_wallet_scope(self):
        engine = create_engine(local_database_url(test=True))
        try:
            with engine.begin() as connection:

                def account(role):
                    return connection.execute(
                        insert(Account.__table__).values(role=role).returning(Account.id)
                    ).scalar_one()

                first_agent, second_agent = account("AGENT"), account("AGENT")
                first_player, second_player, unassigned = (
                    account("PLAYER"),
                    account("PLAYER"),
                    account("PLAYER"),
                )
                assignment = connection.execute(
                    insert(AgentAssignment.__table__)
                    .values(
                        player_account_id=first_player,
                        agent_account_id=first_agent,
                        actor_account_id=first_agent,
                        started_at=func.now() - text("interval '1 minute'"),
                    )
                    .returning(AgentAssignment.id)
                ).scalar_one()
                connection.execute(
                    insert(AgentAssignment.__table__).values(
                        player_account_id=second_player,
                        agent_account_id=second_agent,
                        actor_account_id=second_agent,
                        started_at=func.now() - text("interval '1 minute'"),
                    )
                )
                tokens = {}
                for agent in (first_agent, second_agent):
                    token = secrets.token_urlsafe(32)
                    tokens[agent] = token
                    connection.execute(
                        insert(AccountSession.__table__).values(
                            account_id=agent,
                            role_at_issue="AGENT",
                            token_digest=session_token_digest(token),
                            issued_at=func.now(),
                            last_seen_at=func.now(),
                            idle_expires_at=func.now() + text("interval '30 minutes'"),
                            absolute_expires_at=func.now() + text("interval '12 hours'"),
                        )
                    )
            first = TestClient(app, base_url=ORIGIN, client=("203.0.113.41", 50001))
            second = TestClient(app, base_url=ORIGIN, client=("203.0.113.42", 50002))
            first.cookies.set(SESSION_COOKIE, tokens[first_agent], domain="game.example")
            second.cookies.set(SESSION_COOKIE, tokens[second_agent], domain="game.example")
            with (
                patch.dict("os.environ", CONFIG),
                patch("fairmount_api.private_read_api._configured_engine", return_value=engine),
            ):
                self.assertEqual(
                    first.get("/api/v1/me/players").json(),
                    {"player_ids": [str(first_player)], "next_after": None},
                )
                self.assertEqual(
                    second.get("/api/v1/me/players").json(),
                    {"player_ids": [str(second_player)], "next_after": None},
                )
                allowed = first.get(player_url(first_player))
                self.assertEqual(
                    (allowed.status_code, allowed.json()),
                    (200, {"account_id": str(first_player), "balance": 0}),
                )
                for target in (second_player, unassigned, first_agent):
                    denied = first.get(player_url(target))
                    self.assertEqual(
                        (denied.status_code, denied.json()),
                        (404, {"status": "unavailable"}),
                    )
                self.assertEqual(second.get(player_url(first_player)).status_code, 404)
                with engine.begin() as connection:
                    connection.execute(
                        update(AgentAssignment.__table__)
                        .where(AgentAssignment.id == assignment)
                        .values(ended_at=func.now())
                    )
                    connection.execute(
                        insert(AgentAssignment.__table__).values(
                            player_account_id=first_player,
                            agent_account_id=second_agent,
                            actor_account_id=second_agent,
                        )
                    )
                self.assertEqual(first.get(player_url(first_player)).status_code, 404)
                self.assertEqual(
                    first.get("/api/v1/me/players").json(), {"player_ids": [], "next_after": None}
                )
                self.assertEqual(second.get(player_url(first_player)).status_code, 200)
                self.assertEqual(
                    second.get("/api/v1/me/players").json(),
                    {
                        "player_ids": sorted((str(first_player), str(second_player))),
                        "next_after": None,
                    },
                )
                with engine.begin() as connection:
                    connection.execute(
                        update(Account.__table__)
                        .where(Account.id == first_player)
                        .values(status="DISABLED", disabled_at=func.now())
                    )
                self.assertEqual(second.get(player_url(first_player)).status_code, 404)
                self.assertEqual(second.get(player_url(second_player)).status_code, 200)
                self.assertEqual(
                    second.get("/api/v1/me/players").json(),
                    {"player_ids": [str(second_player)], "next_after": None},
                )
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
