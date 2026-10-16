"""Minimal pending/active credential states, not an activation or login service.

Revision ID: 20261016_06
Revises: 20261016_05

No readable secret is stored. The application must later verify expiry and possession,
atomically consume the secret, enforce MFA and record audit before granting access.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261016_06"
down_revision: str | None = "20261016_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREDENTIAL_STATE_CHECK = """
    (password_hash IS NULL AND password_changed_at IS NULL
     AND initial_secret_digest IS NOT NULL
     AND initial_secret_digest COLLATE "C" ~ '^[0-9a-f]{64}$'
     AND initial_secret_expires_at IS NOT NULL
     AND initial_secret_expires_at = initial_secret_issued_at + INTERVAL '24 hours'
     AND initial_secret_consumed_at IS NULL)
    OR
    (password_hash IS NOT NULL AND password_changed_at IS NOT NULL
     AND password_hash LIKE '$argon2id$%'
     AND initial_secret_digest IS NULL AND initial_secret_expires_at IS NULL
     AND initial_secret_consumed_at IS NOT NULL
     AND initial_secret_consumed_at >= initial_secret_issued_at
     AND password_changed_at >= initial_secret_consumed_at)
"""


def upgrade() -> None:
    op.create_table(
        "account_credentials",
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("initial_secret_digest", sa.String(length=64)),
        sa.Column(
            "initial_secret_issued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("initial_secret_expires_at", sa.DateTime(timezone=True)),
        sa.Column("initial_secret_consumed_at", sa.DateTime(timezone=True)),
        sa.Column("password_hash", sa.Text()),
        sa.Column("password_changed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(CREDENTIAL_STATE_CHECK, name="ck_account_credentials_state"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("account_id"),
    )
    # No active credential row may be reverted to a pending token or reassigned.
    # Reissuance is allowed only while pending and remains a future authorized service.
    op.execute("""
        CREATE FUNCTION protect_active_credential() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.password_hash IS NOT NULL THEN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'Activated credential cannot be deleted in V1'
                        USING ERRCODE = '23514';
                END IF;
                IF NEW.account_id IS DISTINCT FROM OLD.account_id
                   OR NEW.initial_secret_issued_at IS DISTINCT FROM OLD.initial_secret_issued_at
                   OR NEW.initial_secret_consumed_at IS DISTINCT FROM OLD.initial_secret_consumed_at
                   OR NEW.password_hash IS NULL
                   OR NEW.initial_secret_digest IS NOT NULL THEN
                    RAISE EXCEPTION 'Activated credential cannot return to pending'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_account_credentials_active_guard
        BEFORE UPDATE OR DELETE ON account_credentials
        FOR EACH ROW EXECUTE FUNCTION protect_active_credential()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_account_credentials_active_guard ON account_credentials")
    op.execute("DROP FUNCTION protect_active_credential()")
    op.drop_table("account_credentials")
