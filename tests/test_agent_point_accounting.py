"""Assigned-agent point transfers, checked against PostgreSQL source of truth."""

import os
import secrets
import unittest

from fairmount_api.agent_point_accounting import transfer_agent_points
from fairmount_api.db.models import (
    Account,
    AccountSession,
    AccountWallet,
    AgentAssignment,
    PointOperation,
)
from fairmount_api.identity.session_validation import session_token_digest
from fairmount_api.point_accounting import (
    PointActionConflict,
    PointActionUnavailable,
    issue_owner_points,
    transfer_owner_points,
)
from sqlalchemy import create_engine, func, insert, select, text, update

from infrastructure.local_db_url import local_database_url


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class AgentPointAccountingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_engine(local_database_url(test=True))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        self.owner = self.account("OWNER")
        self.agent = self.account("AGENT")
        self.other_agent = self.account("AGENT")
        self.player = self.account("PLAYER")
        self.other_player = self.account("PLAYER")
        self.unassigned = self.account("PLAYER")
        self.assign(self.player, self.agent)
        self.assign(self.other_player, self.other_agent)
        self.agent_token = self.session(self.agent, "AGENT")
        self.owner_token = self.session(self.owner, "OWNER")

    def tearDown(self) -> None:
        self.transaction.rollback()
        self.connection.close()

    def account(self, role):
        return self.connection.execute(
            insert(Account.__table__).values(role=role).returning(Account.id)
        ).scalar_one()

    def assign(self, player, agent):
        return self.connection.execute(
            insert(AgentAssignment.__table__)
            .values(
                player_account_id=player,
                agent_account_id=agent,
                actor_account_id=self.owner,
                started_at=func.now() - text("interval '1 minute'"),
            )
            .returning(AgentAssignment.id)
        ).scalar_one()

    def session(self, account, role):
        token = secrets.token_urlsafe(32)
        is_owner = role == "OWNER"
        self.connection.execute(
            insert(AccountSession.__table__).values(
                account_id=account,
                role_at_issue=role,
                token_digest=session_token_digest(token),
                issued_at=func.now() - text("interval '5 minutes'") if is_owner else func.now(),
                last_seen_at=func.now(),
                idle_expires_at=func.now()
                + text("interval '15 minutes'" if is_owner else "interval '30 minutes'"),
                absolute_expires_at=func.now()
                + text("interval '7 hours 55 minutes'" if is_owner else "interval '12 hours'"),
                mfa_verified_at=func.now() - text("interval '5 minutes'") if is_owner else None,
            )
        )
        return token

    def fund_agent(self, amount=100):
        issue_owner_points(
            self.connection,
            self.owner_token,
            amount=amount,
            reason="seed owner",
            idempotency_key="owner-seed",
        )
        transfer_owner_points(
            self.connection,
            self.owner_token,
            member_account_id=self.agent,
            amount=amount,
            to_member=True,
            reason="fund assigned agent",
            idempotency_key="agent-fund",
        )

    def move(self, player=None, amount=25, to_player=True, key="move", token=None):
        return transfer_agent_points(
            self.connection,
            token or self.agent_token,
            player_account_id=player or self.player,
            amount=amount,
            to_player=to_player,
            reason="agent allocation",
            idempotency_key=key,
        )

    def balance(self, account):
        return self.connection.scalar(
            select(AccountWallet.balance).where(AccountWallet.account_id == account)
        )

    def test_assigned_add_and_return_are_conserved_without_player_password(self) -> None:
        self.fund_agent()
        outgoing = self.move()
        incoming = self.move(amount=10, to_player=False, key="return")
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertNotEqual(outgoing.operation_id, incoming.operation_id)
        self.assertEqual(
            (self.balance(self.owner), self.balance(self.agent), self.balance(self.player)),
            (0, 85, 15),
        )

    def test_replay_requires_identical_intent(self) -> None:
        self.fund_agent()
        original = self.move()
        replay = self.move()
        self.assertEqual(original.operation_id, replay.operation_id)
        self.assertTrue(replay.replayed)
        with self.assertRaises(PointActionConflict), self.connection.begin_nested():
            self.move(amount=30)
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertEqual((self.balance(self.agent), self.balance(self.player)), (75, 25))

    def test_insufficient_source_rejects_entire_transfer(self) -> None:
        self.fund_agent(10)
        with self.assertRaises(PointActionUnavailable), self.connection.begin_nested():
            self.move(amount=11)
        with self.assertRaises(PointActionUnavailable), self.connection.begin_nested():
            self.move(amount=5, to_player=False, key="no-player-balance")
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertEqual((self.balance(self.agent), self.balance(self.player)), (10, 0))
        self.assertEqual(
            self.connection.scalar(select(func.count()).select_from(PointOperation)), 2
        )

    def test_cross_agent_and_owner_managed_players_denied(self) -> None:
        self.fund_agent()
        for player in (self.other_player, self.unassigned):
            with self.subTest(player=player), self.assertRaises(PointActionUnavailable):
                self.move(player=player, key=str(player))
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertEqual(
            (
                self.balance(self.agent),
                self.balance(self.other_player),
                self.balance(self.unassigned),
            ),
            (100, 0, 0),
        )

    def test_disable_and_reassignment_revoke_prior_scope(self) -> None:
        self.fund_agent()
        assignment = self.connection.scalar(
            select(AgentAssignment.id).where(
                AgentAssignment.player_account_id == self.player,
                AgentAssignment.ended_at.is_(None),
            )
        )
        self.connection.execute(
            update(AgentAssignment.__table__)
            .where(AgentAssignment.id == assignment)
            .values(ended_at=func.now())
        )
        self.assign(self.player, self.other_agent)
        with self.assertRaises(PointActionUnavailable):
            self.move(key="reassigned")
        self.connection.execute(
            update(Account.__table__)
            .where(Account.id == self.player)
            .values(status="DISABLED", disabled_at=func.now())
        )
        with self.assertRaises(PointActionUnavailable):
            self.move(key="disabled")
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

    def test_wrong_role_stale_scope_and_bad_stake_denied(self) -> None:
        with self.assertRaises(PointActionUnavailable):
            self.move(token=self.owner_token)
        with self.assertRaises(PointActionUnavailable):
            self.move(amount=True)
        self.connection.execute(
            update(Account.__table__)
            .where(Account.id == self.agent)
            .values(status="DISABLED", disabled_at=func.now())
        )
        with self.assertRaises(PointActionUnavailable):
            self.move(key="agent-disabled")
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


if __name__ == "__main__":
    unittest.main()
