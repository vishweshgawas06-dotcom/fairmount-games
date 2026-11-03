"""Owner provisioning and account lifecycle against PostgreSQL; no HTTP route yet."""

import os
import secrets
import unittest
import uuid

from fairmount_api.db.models import (
    Account,
    AccountCredential,
    AccountSession,
    AgentAssignment,
    PrivateIdentity,
    SecurityEvent,
)
from fairmount_api.identity.account_admin import (
    AccountAdminUnavailable,
    assign_player,
    set_account_enabled,
    unassign_player,
)
from fairmount_api.identity.credentials import initial_secret_digest
from fairmount_api.identity.member_login import MemberLoginUnavailable, issue_member_session
from fairmount_api.identity.provisioning import (
    ProvisioningUnavailable,
    provision_agent,
    provision_player,
)
from fairmount_api.identity.session_validation import session_token_digest
from sqlalchemy import create_engine, func, insert, select, text, update

from infrastructure.local_db_url import local_database_url


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "Disposable PostgreSQL test DB required"
)
class OperatorLifecycleTests(unittest.TestCase):
    """Committed fixtures: audit and identity rows are immutable by design."""

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(local_database_url(test=True))

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        # A rolled-back owner per test: committed owners belong to other modules
        # and would make `bootstrap_owner` refuse a fresh environment.
        self.owner_id = self.connection.execute(
            insert(Account.__table__).values(role="OWNER").returning(Account.id)
        ).scalar_one()
        self.owner_token = self.owner_session()
        self._counter = uuid.uuid4().hex[:8]
        self._players = 0

    def tearDown(self):
        self.transaction.rollback()
        self.connection.close()

    # -- fixtures ---------------------------------------------------------
    def owner_session(self, *, mfa_age="5 minutes", role="OWNER", account=None):
        """Create (or replace) one live session; OWNER sessions need MFA recency."""
        token = secrets.token_urlsafe(32)
        target = account or self.owner_id
        self.connection.execute(
            update(AccountSession.__table__)
            .where(AccountSession.account_id == target, AccountSession.revoked_at.is_(None))
            .values(revoked_at=func.now())
        )
        self.connection.execute(
            insert(AccountSession.__table__).values(
                account_id=target,
                role_at_issue=role,
                token_digest=session_token_digest(token),
                issued_at=func.now() - text(f"interval '{mfa_age}'"),
                last_seen_at=func.now(),
                idle_expires_at=func.now() + text("interval '15 minutes'"),
                absolute_expires_at=func.now() + text(f"interval '8 hours' - interval '{mfa_age}'"),
                mfa_verified_at=func.now() - text(f"interval '{mfa_age}'"),
            )
        )
        return token

    def member_session(self, account_id, role):
        """One live member session; AGENT and PLAYER carry no MFA timestamp."""
        token = secrets.token_urlsafe(32)
        hours = 12 if role == "AGENT" else 24
        self.connection.execute(
            update(AccountSession.__table__)
            .where(AccountSession.account_id == account_id, AccountSession.revoked_at.is_(None))
            .values(revoked_at=func.now())
        )
        self.connection.execute(
            insert(AccountSession.__table__).values(
                account_id=account_id,
                role_at_issue=role,
                token_digest=session_token_digest(token),
                issued_at=func.now(),
                last_seen_at=func.now(),
                idle_expires_at=func.now() + text("interval '30 minutes'"),
                absolute_expires_at=func.now() + text(f"interval '{hours} hours'"),
            )
        )
        return token

    def agent(self, **kwargs):
        return provision_agent(self.connection, self.owner_token, **kwargs)

    def player(self, username=None):
        self._players += 1
        return provision_player(
            self.connection,
            self.owner_token,
            username=username or f"player_{self._counter}{self._players}",
        )

    def status_of(self, account_id):
        return self.connection.scalar(select(Account.status).where(Account.id == account_id))

    def events(self, target_id):
        """Sorted event types: `now()` ties inside one transaction carry no order."""

        return sorted(
            self.connection.scalars(
                select(SecurityEvent.event_type).where(SecurityEvent.target_account_id == target_id)
            )
        )

    def current_assignment(self, player_id):
        return self.connection.execute(
            select(AgentAssignment.agent_account_id, AgentAssignment.actor_account_id).where(
                AgentAssignment.player_account_id == player_id,
                AgentAssignment.ended_at.is_(None),
            )
        ).one_or_none()

    def assignment_count(self, player_id):
        return self.connection.scalar(
            select(func.count())
            .select_from(AgentAssignment)
            .where(AgentAssignment.player_account_id == player_id)
        )

    # -- provisioning -----------------------------------------------------
    def test_agent_provisioning_stores_only_a_digest_and_audits(self):
        provisioned = self.agent()
        self.assertRegex(provisioned.login_id, r"^AGT-[A-Z2-9]{10}$")
        self.assertNotIn(provisioned.secret, repr(provisioned))  # never rendered
        self.assertGreater(provisioned.expires_at, self.connection.scalar(select(func.now())))
        stored = self.connection.execute(
            select(
                PrivateIdentity.login_identifier,
                PrivateIdentity.login_kind,
                AccountCredential.initial_secret_digest,
                AccountCredential.password_hash,
            )
            .join(
                AccountCredential,
                AccountCredential.account_id == PrivateIdentity.account_id,
            )
            .where(PrivateIdentity.account_id == provisioned.account_id)
        ).one()
        self.assertEqual(
            (stored.login_identifier, stored.login_kind),
            (provisioned.login_id.lower(), "AGENT"),
        )
        self.assertNotEqual(stored.initial_secret_digest, provisioned.secret)
        self.assertEqual(stored.initial_secret_digest, initial_secret_digest(provisioned.secret))
        self.assertIsNone(stored.password_hash)  # cannot log in before activation
        self.assertEqual(self.events(provisioned.account_id), ["INITIAL_CREDENTIAL_ISSUED"])
        # No plaintext secret anywhere in the audit row.
        for column in ("event_type", "source"):
            value = self.connection.scalar(
                select(getattr(SecurityEvent, column)).where(
                    SecurityEvent.target_account_id == provisioned.account_id
                )
            )
            self.assertNotIn(provisioned.secret, value)

    def test_agent_id_must_be_valid_and_unique(self):
        fixed = self.agent(agent_id="AGT-ABCDEFGHJK")
        self.assertEqual(fixed.login_id, "AGT-ABCDEFGHJK")
        with self.assertRaises(ProvisioningUnavailable):
            self.agent(agent_id="AGT-ABCDEFGHJK")  # duplicate
        for invalid in ("AGT-ABCDEFGHJ0", "agent", "AGT-ABC", "", 123):
            with self.subTest(invalid=invalid), self.assertRaises(ProvisioningUnavailable):
                self.agent(agent_id=invalid)

    def test_player_usernames_are_canonical_and_reserved_names_rejected(self):
        provisioned = self.player("Alice_01")
        self.assertEqual(provisioned.login_id, "alice_01")
        self.assertEqual(
            self.connection.scalar(
                select(PrivateIdentity.login_identifier).where(
                    PrivateIdentity.account_id == provisioned.account_id
                )
            ),
            "alice_01",
        )
        for bad in ("admin", "owner", "ab", "1alice", "alice!", "agt-abcdefghjk", "x" * 33):
            with self.subTest(bad=bad), self.assertRaises(ProvisioningUnavailable):
                self.player(bad)
        with self.assertRaises(ProvisioningUnavailable):
            self.player("alice_01")  # duplicate

    def test_provisioned_member_cannot_log_in_until_activation(self):
        provisioned = self.agent()
        with self.assertRaises(MemberLoginUnavailable):
            issue_member_session(
                self.connection, "AGENT", provisioned.login_id, "some-long-passphrase-1"
            )

    def test_provisioning_requires_a_live_owner_with_fresh_mfa(self):
        stale = self.owner_session(mfa_age="45 minutes")
        for token in (stale, "not-a-token", "", None):
            with self.subTest(token=token), self.assertRaises(ProvisioningUnavailable):
                provision_agent(self.connection, token)

    def test_agent_or_player_session_cannot_provision_sub_agents(self):
        agent = self.agent()
        agent_token = self.member_session(agent.account_id, "AGENT")
        player = self.player()
        player_token = self.member_session(player.account_id, "PLAYER")
        for token in (agent_token, player_token):
            with self.subTest(role_token=token[:8]), self.assertRaises(ProvisioningUnavailable):
                provision_agent(self.connection, token)
        # No sub-agent: only the owner's two members exist for this test.
        self.assertIsNone(
            self.connection.scalar(
                select(PrivateIdentity.account_id).where(
                    PrivateIdentity.account_id.notin_([agent.account_id, player.account_id]),
                    PrivateIdentity.login_kind == "AGENT",
                    PrivateIdentity.login_identifier.like("agt-%"),
                )
            )
        )

    # -- assignment -------------------------------------------------------
    def test_assignment_is_audited_and_reassignment_closes_the_previous_row(self):
        first_agent = self.agent()
        second_agent = self.agent()
        player = self.player()
        assignment = assign_player(
            self.connection,
            self.owner_token,
            player_id=player.account_id,
            agent_id=first_agent.account_id,
        )
        self.assertEqual(
            self.current_assignment(player.account_id),
            (first_agent.account_id, self.owner_id),
        )
        # Idempotent: assigning the same agent again does not create history.
        self.assertEqual(
            assign_player(
                self.connection,
                self.owner_token,
                player_id=player.account_id,
                agent_id=first_agent.account_id,
            ),
            assignment,
        )
        self.assertEqual(self.assignment_count(player.account_id), 1)
        assign_player(
            self.connection,
            self.owner_token,
            player_id=player.account_id,
            agent_id=second_agent.account_id,
        )
        self.assertEqual(self.current_assignment(player.account_id)[0], second_agent.account_id)
        self.assertEqual(self.assignment_count(player.account_id), 2)
        current_rows = self.connection.scalar(
            select(func.count())
            .select_from(AgentAssignment)
            .where(
                AgentAssignment.player_account_id == player.account_id,
                AgentAssignment.ended_at.is_(None),
            )
        )
        self.assertEqual(current_rows, 1)
        self.assertEqual(
            self.events(player.account_id),
            [
                "AGENT_ASSIGNED",
                "AGENT_ASSIGNED",
                "AGENT_UNASSIGNED",
                "INITIAL_CREDENTIAL_ISSUED",
            ],
        )

    def test_unassign_is_idempotent(self):
        agent = self.agent()
        player = self.player()
        assign_player(
            self.connection,
            self.owner_token,
            player_id=player.account_id,
            agent_id=agent.account_id,
        )
        self.assertTrue(
            unassign_player(self.connection, self.owner_token, player_id=player.account_id)
        )
        self.assertFalse(
            unassign_player(self.connection, self.owner_token, player_id=player.account_id)
        )
        self.assertIsNone(self.current_assignment(player.account_id))

    def test_assignment_rejects_wrong_roles_disabled_targets_and_bad_tokens(self):
        agent = self.agent()
        player = self.player()
        another_player = self.player()
        # A player is not an agent, and the owner is not an assignment target.
        for agent_id in (another_player.account_id, self.owner_id, uuid.uuid4(), "not-a-uuid"):
            with self.subTest(agent_id=agent_id), self.assertRaises(AccountAdminUnavailable):
                assign_player(
                    self.connection,
                    self.owner_token,
                    player_id=player.account_id,
                    agent_id=agent_id,
                )
        with self.assertRaises(AccountAdminUnavailable):
            assign_player(
                self.connection,
                self.owner_token,
                player_id=agent.account_id,  # role mismatch
                agent_id=agent.account_id,
            )
        set_account_enabled(
            self.connection, self.owner_token, account_id=agent.account_id, enabled=False
        )
        with self.assertRaises(AccountAdminUnavailable):
            assign_player(
                self.connection,
                self.owner_token,
                player_id=player.account_id,
                agent_id=agent.account_id,
            )
        stale = self.owner_session(mfa_age="30 minutes")
        with self.assertRaises(AccountAdminUnavailable):
            assign_player(
                self.connection,
                stale,
                player_id=player.account_id,
                agent_id=agent.account_id,
            )

    # -- enable / disable -------------------------------------------------
    def test_disabling_a_player_revokes_its_live_session_and_audits(self):
        player = self.player()
        token = self.member_session(player.account_id, "PLAYER")
        self.assertIsNotNone(
            self.connection.scalar(
                select(AccountSession.account_id).where(
                    AccountSession.token_digest == session_token_digest(token),
                    AccountSession.revoked_at.is_(None),
                )
            )
        )
        status = set_account_enabled(
            self.connection, self.owner_token, account_id=player.account_id, enabled=False
        )
        self.assertEqual(status, "DISABLED")
        self.assertEqual(self.status_of(player.account_id), "DISABLED")
        self.assertIsNotNone(
            self.connection.scalar(
                select(Account.disabled_at).where(Account.id == player.account_id)
            )
        )
        self.assertIsNone(
            self.connection.scalar(
                select(AccountSession.account_id).where(
                    AccountSession.token_digest == session_token_digest(token),
                    AccountSession.revoked_at.is_(None),
                )
            )
        )
        self.assertEqual(self.events(player.account_id).count("ACCOUNT_DISABLED"), 1)
        # Re-enabling clears disabled_at, is audited once, and is idempotent.
        self.assertEqual(
            set_account_enabled(
                self.connection, self.owner_token, account_id=player.account_id, enabled=True
            ),
            "ENABLED",
        )
        self.assertIsNone(
            self.connection.scalar(
                select(Account.disabled_at).where(Account.id == player.account_id)
            )
        )
        self.assertEqual(
            set_account_enabled(
                self.connection, self.owner_token, account_id=player.account_id, enabled=True
            ),
            "ENABLED",
        )
        self.assertEqual(
            [e for e in self.events(player.account_id) if e.startswith("ACCOUNT_")],
            ["ACCOUNT_DISABLED", "ACCOUNT_ENABLED"],
        )

    def test_the_sole_owner_cannot_be_disabled_or_targeted(self):
        with self.assertRaises(AccountAdminUnavailable):
            set_account_enabled(
                self.connection, self.owner_token, account_id=self.owner_id, enabled=False
            )
        self.assertEqual(self.status_of(self.owner_id), "ENABLED")

    def test_enable_disable_rejects_bad_input(self):
        agent = self.agent()
        for enabled in ("false", 0, None):
            with self.subTest(enabled=enabled), self.assertRaises(AccountAdminUnavailable):
                set_account_enabled(
                    self.connection, self.owner_token, account_id=agent.account_id, enabled=enabled
                )
        for account_id in (uuid.uuid4(), "not-a-uuid", None):
            with self.subTest(account_id=account_id), self.assertRaises(AccountAdminUnavailable):
                set_account_enabled(
                    self.connection, self.owner_token, account_id=account_id, enabled=False
                )

    def test_lifecycle_events_carry_no_reason_or_secret_columns(self):
        player = self.player()
        agent = self.agent()
        assign_player(
            self.connection,
            self.owner_token,
            player_id=player.account_id,
            agent_id=agent.account_id,
        )
        set_account_enabled(
            self.connection, self.owner_token, account_id=player.account_id, enabled=False
        )
        rows = self.connection.execute(
            select(SecurityEvent.event_type).where(
                SecurityEvent.target_account_id == player.account_id
            )
        ).all()
        self.assertTrue(rows)
        stored = " ".join(row[0] for row in rows)
        self.assertNotIn(player.secret, stored)
        self.assertNotIn(agent.secret, stored)


if __name__ == "__main__":
    unittest.main()
