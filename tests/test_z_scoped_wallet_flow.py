"""Committed agent HTTP resource scope against disposable migrated PostgreSQL.

This fixture seeds already issued test sessions and assignments; it is NOT an
agent registration/login test. Immutable wallet rows require disposable CI DB.
"""

import os
import secrets
import unittest
from unittest.mock import patch

from fairmount_api.db.models import Account, AccountSession, AgentAssignment
from fairmount_api.identity.http_boundary import SESSION_COOKIE
from fairmount_api.identity.session_validation import session_token_digest
from fairmount_api.main import app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, insert, text, update

from infrastructure.local_db_url import local_database_url

ORIGIN = "https://game.example"


def player_url(player):
    return f"/api/v1/players/{player}/wallet"


CONFIG = {"FAIRMOUNT_AUTH_EDGE_MODE": "direct-tls", "FAIRMOUNT_PUBLIC_ORIGIN": ORIGIN}


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "Disposable PostgreSQL test DB required"
)
class ScopedWalletHTTPFlowTests(unittest.TestCase):
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
                self.assertEqual(second.get(player_url(first_player)).status_code, 200)
                with engine.begin() as connection:
                    connection.execute(
                        update(Account.__table__)
                        .where(Account.id == first_player)
                        .values(status="DISABLED", disabled_at=func.now())
                    )
                self.assertEqual(second.get(player_url(first_player)).status_code, 404)
                self.assertEqual(second.get(player_url(second_player)).status_code, 200)
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
