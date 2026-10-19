"""Minimal immutable credential/security event journal; no workflow yet.

Revision ID: 20261016_07
Revises: 20261016_06

No free-form data, secret, digest, password hash or OTP may be stored in an event row.
Future retention/deletion needs a separate approved D-02 review.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261016_07"
down_revision: str | None = "20261016_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SECURITY_EVENT_CHECK = """
    event_type IN (
        'OWNER_BOOTSTRAP_ISSUED', 'OWNER_BOOTSTRAP_REISSUED',
        'INITIAL_CREDENTIAL_ISSUED', 'INITIAL_CREDENTIAL_CONSUMED',
        'PASSWORD_CHANGED', 'OWNER_MFA_ENROLLED'
    ) AND source IN ('LOCAL_CLI', 'DASHBOARD', 'SELF_SERVICE')
    AND (actor_account_id IS NOT NULL OR
         (source = 'LOCAL_CLI' AND event_type IN
          ('OWNER_BOOTSTRAP_ISSUED', 'OWNER_BOOTSTRAP_REISSUED')))
"""


def upgrade() -> None:
    op.create_table(
        "security_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("actor_account_id", postgresql.UUID(as_uuid=True)),
        sa.Column("target_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(SECURITY_EVENT_CHECK, name="ck_security_events_valid"),
        sa.ForeignKeyConstraint(["actor_account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["target_account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_security_events_target_time", "security_events", ["target_account_id", "occurred_at"]
    )
    op.execute("""
        CREATE FUNCTION protect_security_event() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Security events are append-only'
                USING ERRCODE = '23514';
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_security_events_append_only
        BEFORE UPDATE OR DELETE ON security_events
        FOR EACH ROW EXECUTE FUNCTION protect_security_event()
    """)
    op.execute("""
        CREATE TRIGGER trg_security_events_no_truncate
        BEFORE TRUNCATE ON security_events
        FOR EACH STATEMENT EXECUTE FUNCTION protect_security_event()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_security_events_no_truncate ON security_events")
    op.execute("DROP TRIGGER trg_security_events_append_only ON security_events")
    op.execute("DROP FUNCTION protect_security_event()")
    op.drop_index("ix_security_events_target_time", table_name="security_events")
    op.drop_table("security_events")
