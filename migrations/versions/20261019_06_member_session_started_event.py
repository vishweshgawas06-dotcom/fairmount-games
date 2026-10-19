"""Audit internal agent/player session issuance without a bearer token.

Revision ID: 20261019_06
Revises: 20261019_05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261019_06"
down_revision: str | None = "20261019_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _event_check(include_member: bool) -> str:
    extra = ", 'MEMBER_SESSION_STARTED'" if include_member else ""
    return f"""
    event_type IN (
        'OWNER_BOOTSTRAP_ISSUED', 'OWNER_BOOTSTRAP_REISSUED',
        'INITIAL_CREDENTIAL_ISSUED', 'INITIAL_CREDENTIAL_CONSUMED',
        'PASSWORD_CHANGED', 'OWNER_MFA_ENROLLED', 'OWNER_MFA_VERIFIED',
        'OWNER_SESSION_STARTED', 'SESSION_REVOKED'{extra}
    ) AND source IN ('LOCAL_CLI', 'DASHBOARD', 'SELF_SERVICE')
    AND (actor_account_id IS NOT NULL OR
         (source = 'LOCAL_CLI' AND event_type IN
          ('OWNER_BOOTSTRAP_ISSUED', 'OWNER_BOOTSTRAP_REISSUED')))
"""


def upgrade() -> None:
    op.drop_constraint("ck_security_events_valid", "security_events", type_="check")
    op.create_check_constraint("ck_security_events_valid", "security_events", _event_check(True))


def downgrade() -> None:
    # Do not discard immutable audit rows to force an unsafe downgrade.
    op.drop_constraint("ck_security_events_valid", "security_events", type_="check")
    op.create_check_constraint("ck_security_events_valid", "security_events", _event_check(False))
