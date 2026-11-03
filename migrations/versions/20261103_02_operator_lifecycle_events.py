"""Extend the security-event journal with operator lifecycle actions.

Revision ID: 20261103_02
Revises: 20261103_01

Adds only event *types*. The existing constraints still require an actor, a
non-null target and one of the approved sources, and the table stays
append-only. No credentials, secrets, digests or free-form reasons may be
stored in an event row; D-02 retention is still undecided.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261103_02"
down_revision: str | None = "20261103_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_TYPES = """
    event_type IN (
        'OWNER_BOOTSTRAP_ISSUED', 'OWNER_BOOTSTRAP_REISSUED',
        'INITIAL_CREDENTIAL_ISSUED', 'INITIAL_CREDENTIAL_CONSUMED',
        'PASSWORD_CHANGED', 'OWNER_MFA_ENROLLED', 'OWNER_MFA_VERIFIED',
        'OWNER_SESSION_STARTED', 'SESSION_REVOKED', 'MEMBER_SESSION_STARTED',
        'ACCOUNT_ENABLED', 'ACCOUNT_DISABLED',
        'AGENT_ASSIGNED', 'AGENT_UNASSIGNED'
    ) AND source IN ('LOCAL_CLI', 'DASHBOARD', 'SELF_SERVICE')
    AND (actor_account_id IS NOT NULL OR
         (source = 'LOCAL_CLI' AND event_type IN
          ('OWNER_BOOTSTRAP_ISSUED', 'OWNER_BOOTSTRAP_REISSUED')))
"""

_PREVIOUS_EVENT_TYPES = """
    event_type IN (
        'OWNER_BOOTSTRAP_ISSUED', 'OWNER_BOOTSTRAP_REISSUED',
        'INITIAL_CREDENTIAL_ISSUED', 'INITIAL_CREDENTIAL_CONSUMED',
        'PASSWORD_CHANGED', 'OWNER_MFA_ENROLLED', 'OWNER_MFA_VERIFIED',
        'OWNER_SESSION_STARTED', 'SESSION_REVOKED', 'MEMBER_SESSION_STARTED'
    ) AND source IN ('LOCAL_CLI', 'DASHBOARD', 'SELF_SERVICE')
    AND (actor_account_id IS NOT NULL OR
         (source = 'LOCAL_CLI' AND event_type IN
          ('OWNER_BOOTSTRAP_ISSUED', 'OWNER_BOOTSTRAP_REISSUED')))
"""


def upgrade() -> None:
    op.drop_constraint("ck_security_events_valid", "security_events", type_="check")
    op.create_check_constraint("ck_security_events_valid", "security_events", _EVENT_TYPES)


def downgrade() -> None:
    # Refuse to narrow the constraint while lifecycle events exist: that would
    # either fail halfway or silently bless an inconsistent state.
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM security_events
                 WHERE event_type IN (
                    'ACCOUNT_ENABLED', 'ACCOUNT_DISABLED',
                    'AGENT_ASSIGNED', 'AGENT_UNASSIGNED'
                 )
            ) THEN
                RAISE EXCEPTION 'refusing to drop lifecycle audit event types';
            END IF;
        END $$
        """
    )
    op.drop_constraint("ck_security_events_valid", "security_events", type_="check")
    op.create_check_constraint(
        "ck_security_events_valid", "security_events", _PREVIOUS_EVENT_TYPES
    )
