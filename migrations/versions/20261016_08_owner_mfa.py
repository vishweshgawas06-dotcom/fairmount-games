"""Encrypted owner factor and hashed recovery-code storage, without enrollment.

Revision ID: 20261016_08
Revises: 20261016_07

No encryption key or plaintext seed/code is stored here. Service authorization,
confirmation, rate limits, audit and atomic verification are separate work.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261016_08"
down_revision: str | None = "20261016_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "owner_mfa",
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_role", sa.String(length=16), nullable=False, server_default="OWNER"),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("nonce", sa.String(length=16), nullable=False),
        sa.Column("ciphertext", sa.String(length=64), nullable=False),
        sa.Column("last_accepted_step", sa.BigInteger()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "account_role = 'OWNER' AND key_version > 0 "
            "AND nonce COLLATE \"C\" ~ '^[A-Za-z0-9_-]{16}$' "
            "AND ciphertext COLLATE \"C\" ~ '^[A-Za-z0-9_-]{64}$' "
            "AND (last_accepted_step IS NULL OR last_accepted_step >= 0) "
            "AND (confirmed_at IS NULL OR confirmed_at >= created_at) "
            "AND (confirmed_at IS NOT NULL OR last_accepted_step IS NULL)",
            name="ck_owner_mfa_structure",
        ),
        sa.ForeignKeyConstraint(
            ["account_id", "account_role"],
            ["accounts.id", "accounts.role"],
            name="fk_owner_mfa_role",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("account_id"),
    )
    op.create_table(
        "owner_recovery_codes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("owner_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column(
            "issued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "digest COLLATE \"C\" ~ '^[0-9a-f]{64}$' "
            "AND (consumed_at IS NULL OR consumed_at >= issued_at)",
            name="ck_owner_recovery_code_structure",
        ),
        sa.ForeignKeyConstraint(
            ["owner_account_id"], ["owner_mfa.account_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_account_id", "digest", name="uq_owner_recovery_code_digest"),
    )
    op.execute("""
        CREATE FUNCTION protect_consumed_recovery_code() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
                RAISE EXCEPTION 'Recovery code history cannot be deleted in V1'
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.owner_account_id IS DISTINCT FROM OLD.owner_account_id
               OR NEW.digest IS DISTINCT FROM OLD.digest
               OR NEW.issued_at IS DISTINCT FROM OLD.issued_at
               OR OLD.consumed_at IS NOT NULL
               OR NEW.consumed_at IS NULL THEN
                RAISE EXCEPTION 'Recovery code can only be consumed once'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_owner_recovery_code_once
        BEFORE UPDATE OR DELETE ON owner_recovery_codes
        FOR EACH ROW EXECUTE FUNCTION protect_consumed_recovery_code()
    """)
    op.execute("""
        CREATE TRIGGER trg_owner_recovery_code_no_truncate
        BEFORE TRUNCATE ON owner_recovery_codes
        FOR EACH STATEMENT EXECUTE FUNCTION protect_consumed_recovery_code()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_owner_recovery_code_no_truncate ON owner_recovery_codes")
    op.execute("DROP TRIGGER trg_owner_recovery_code_once ON owner_recovery_codes")
    op.execute("DROP FUNCTION protect_consumed_recovery_code()")
    op.drop_table("owner_recovery_codes")
    op.drop_table("owner_mfa")
