"""Audit successful two-factor owner session creation without storing a token.

Revision ID: 20261019_03
Revises: 20261019_02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261019_03"
down_revision: str | None = "20261019_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _event_check(include_session: bool) -> str:
    extra = ", 'OWNER_SESSION_STARTED'" if include_session else ""
    return f"""
    event_type IN (
        'OWNER_BOOTSTRAP_ISSUED', 'OWNER_BOOTSTRAP_REISSUED',
        'INITIAL_CREDENTIAL_ISSUED', 'INITIAL_CREDENTIAL_CONSUMED',
        'PASSWORD_CHANGED', 'OWNER_MFA_ENROLLED', 'OWNER_MFA_VERIFIED'{extra}
    ) AND source IN ('LOCAL_CLI', 'DASHBOARD', 'SELF_SERVICE')
    AND (actor_account_id IS NOT NULL OR
         (source = 'LOCAL_CLI' AND event_type IN
          ('OWNER_BOOTSTRAP_ISSUED', 'OWNER_BOOTSTRAP_REISSUED')))
"""


def upgrade() -> None:
    op.drop_constraint("ck_security_events_valid", "security_events", type_="check")
    op.create_check_constraint("ck_security_events_valid", "security_events", _event_check(True))


def downgrade() -> None:
    # Never discard immutable audit rows to force a downgrade.
    op.drop_constraint("ck_security_events_valid", "security_events", type_="check")
    op.create_check_constraint("ck_security_events_valid", "security_events", _event_check(False))
