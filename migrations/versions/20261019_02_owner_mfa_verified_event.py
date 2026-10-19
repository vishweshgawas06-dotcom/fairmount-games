"""Allow an append-only, factor-free owner MFA success event.

Revision ID: 20261019_02
Revises: 20261019_01

A SELF_SERVICE actor identifies the submitted owner account, not a logged-in
session. Rate-limited failure recording remains a separate request-boundary task.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261019_02"
down_revision: str | None = "20261019_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _event_check(with_mfa_verified: bool) -> str:
    added = ", 'OWNER_MFA_VERIFIED'" if with_mfa_verified else ""
    return f"""
    event_type IN (
        'OWNER_BOOTSTRAP_ISSUED', 'OWNER_BOOTSTRAP_REISSUED',
        'INITIAL_CREDENTIAL_ISSUED', 'INITIAL_CREDENTIAL_CONSUMED',
        'PASSWORD_CHANGED', 'OWNER_MFA_ENROLLED'{added}
    ) AND source IN ('LOCAL_CLI', 'DASHBOARD', 'SELF_SERVICE')
    AND (actor_account_id IS NOT NULL OR
         (source = 'LOCAL_CLI' AND event_type IN
          ('OWNER_BOOTSTRAP_ISSUED', 'OWNER_BOOTSTRAP_REISSUED')))
"""


def upgrade() -> None:
    op.drop_constraint("ck_security_events_valid", "security_events", type_="check")
    op.create_check_constraint("ck_security_events_valid", "security_events", _event_check(True))


def downgrade() -> None:
    # Downgrading after any verification event requires explicit retention review.
    op.drop_constraint("ck_security_events_valid", "security_events", type_="check")
    op.create_check_constraint("ck_security_events_valid", "security_events", _event_check(False))
