"""Pseudonymous authentication failure window and immutable audit.

Revision ID: 20261023_03
Revises: 20261023_02
No login or MFA route is enabled by this migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261023_03"
down_revision: str | None = "20261023_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_attempt_buckets",
        sa.Column("key_digest", sa.String(64), primary_key=True),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failures", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint(
            "key_digest COLLATE \"C\" ~ '^[0-9a-f]{64}$'", name="ck_auth_buckets_key"
        ),
        sa.CheckConstraint("failures >= 0", name="ck_auth_buckets_nonnegative"),
    )
    op.create_table(
        "auth_failure_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("subject_digest", sa.String(64), nullable=False),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("surface", sa.String(24), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "subject_digest COLLATE \"C\" ~ '^[0-9a-f]{64}$' AND "
            "source_digest COLLATE \"C\" ~ '^[0-9a-f]{64}$' AND "
            "surface IN ('OWNER_LOGIN','MEMBER_LOGIN','OWNER_MFA') AND "
            "outcome IN ('FAILED','THROTTLED')",
            name="ck_auth_failure_events_shape",
        ),
    )
    op.create_index("ix_auth_failure_events_time", "auth_failure_events", ["occurred_at"])
    op.execute("""
        CREATE FUNCTION fairmount_guard_auth_failure_event() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'authentication failure audit is immutable';
        END $$
    """)
    op.execute("""
        CREATE TRIGGER tr_auth_failure_immutable BEFORE UPDATE OR DELETE ON auth_failure_events
        FOR EACH ROW EXECUTE FUNCTION fairmount_guard_auth_failure_event()
    """)
    op.execute("""
        CREATE TRIGGER tr_auth_failure_no_truncate BEFORE TRUNCATE ON auth_failure_events
        FOR EACH STATEMENT EXECUTE FUNCTION fairmount_guard_auth_failure_event()
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM auth_failure_events) OR
               EXISTS (SELECT 1 FROM auth_attempt_buckets) THEN
                RAISE EXCEPTION 'refusing to drop authentication failure controls';
            END IF;
        END $$
    """)
    op.drop_index("ix_auth_failure_events_time", table_name="auth_failure_events")
    op.drop_table("auth_failure_events")
    op.drop_table("auth_attempt_buckets")
    op.execute("DROP FUNCTION fairmount_guard_auth_failure_event()")
