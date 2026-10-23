"""UUID-linked wallet, reserve and paired append-only point journal.

Revision ID: 20261023_01
Revises: 20261019_06

No betting/transfer route is enabled by this structural migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261023_01"
down_revision: str | None = "20261019_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POINT_OPERATION_CHECK = """
    kind IN ('OWNER_ISSUE', 'OWNER_TRANSFER', 'AGENT_TRANSFER',
             'RESERVE_FUND', 'RESERVE_WITHDRAW', 'BET_STAKE',
             'PAYOUT', 'VOID_REFUND', 'AGENT_DISABLE_RETURN')
    AND amount > 0 AND length(btrim(reason)) > 0 AND length(idempotency_key) > 0
    AND request_fingerprint COLLATE "C" ~ '^[0-9a-f]{64}$'
    AND (
        (kind = 'OWNER_ISSUE' AND actor_role = 'OWNER'
         AND source_wallet_id IS NULL AND NOT source_reserve
         AND target_wallet_id IS NOT NULL
         AND target_wallet_id = actor_account_id AND NOT target_reserve)
        OR (kind = 'OWNER_TRANSFER' AND actor_role = 'OWNER'
            AND NOT source_reserve AND NOT target_reserve
            AND source_wallet_id IS NOT NULL AND target_wallet_id IS NOT NULL
            AND (source_wallet_id = actor_account_id OR target_wallet_id = actor_account_id))
        OR (kind = 'AGENT_TRANSFER' AND actor_role = 'AGENT'
            AND NOT source_reserve AND NOT target_reserve
            AND source_wallet_id IS NOT NULL AND target_wallet_id IS NOT NULL
            AND (source_wallet_id = actor_account_id OR target_wallet_id = actor_account_id))
        OR (kind = 'AGENT_DISABLE_RETURN' AND actor_role = 'OWNER'
            AND NOT source_reserve AND NOT target_reserve
            AND source_wallet_id IS NOT NULL AND target_wallet_id = actor_account_id)
        OR (kind = 'RESERVE_FUND' AND actor_role = 'OWNER'
            AND source_wallet_id IS NOT NULL
            AND source_wallet_id = actor_account_id
            AND NOT source_reserve AND target_wallet_id IS NULL AND target_reserve)
        OR (kind = 'RESERVE_WITHDRAW' AND actor_role = 'OWNER'
            AND source_wallet_id IS NULL AND source_reserve
            AND target_wallet_id IS NOT NULL AND target_wallet_id = actor_account_id
            AND NOT target_reserve)
        OR (kind = 'BET_STAKE' AND actor_role = 'PLAYER'
            AND source_wallet_id IS NOT NULL AND source_wallet_id = actor_account_id
            AND NOT source_reserve AND target_wallet_id IS NULL AND target_reserve
            AND context_id IS NOT NULL)
        OR (kind IN ('PAYOUT', 'VOID_REFUND') AND actor_role = 'OWNER'
            AND source_wallet_id IS NULL AND source_reserve
            AND target_wallet_id IS NOT NULL AND NOT target_reserve
            AND context_id IS NOT NULL)
    )
    AND (source_wallet_id IS NULL OR target_wallet_id IS NULL
         OR source_wallet_id <> target_wallet_id)
"""


def upgrade() -> None:
    op.create_table(
        "account_wallets",
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("balance", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint("balance >= 0", name="ck_account_wallets_nonnegative"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("account_id"),
    )
    op.create_table(
        "game_reserve",
        sa.Column("id", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("balance", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_game_reserve_singleton"),
        sa.CheckConstraint("balance >= 0", name="ck_game_reserve_nonnegative"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("INSERT INTO game_reserve(id) VALUES (1)")
    # Existing owner/agent/player rows get zero balances. New accounts get a wallet
    # in the same transaction, without creating an issuance ledger entry.
    op.execute("INSERT INTO account_wallets(account_id) SELECT id FROM accounts")
    op.execute("""
        CREATE FUNCTION fairmount_create_account_wallet() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            INSERT INTO account_wallets(account_id) VALUES (NEW.id);
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER tr_account_wallet_create AFTER INSERT ON accounts
        FOR EACH ROW EXECUTE FUNCTION fairmount_create_account_wallet()
    """)
    op.create_table(
        "point_operations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("actor_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_role", sa.String(16), nullable=False),
        sa.Column("source_wallet_id", postgresql.UUID(as_uuid=True)),
        sa.Column("target_wallet_id", postgresql.UUID(as_uuid=True)),
        sa.Column("source_reserve", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("target_reserve", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("context_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(POINT_OPERATION_CHECK, name="ck_point_operations_shape"),
        sa.ForeignKeyConstraint(
            ["actor_account_id", "actor_role"],
            ["accounts.id", "accounts.role"],
            name="fk_point_operations_actor_role",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_wallet_id"], ["account_wallets.account_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["target_wallet_id"], ["account_wallets.account_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "actor_account_id", "idempotency_key", name="uq_point_operations_actor_key"
        ),
    )
    op.create_table(
        "point_ledger_entries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("wallet_account_id", postgresql.UUID(as_uuid=True)),
        sa.Column("reserve_id", sa.SmallInteger()),
        sa.Column("delta", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(wallet_account_id IS NOT NULL) <> (reserve_id IS NOT NULL) AND delta <> 0",
            name="ck_point_ledger_entries_shape",
        ),
        sa.ForeignKeyConstraint(["operation_id"], ["point_operations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["wallet_account_id"], ["account_wallets.account_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["reserve_id"], ["game_reserve.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "operation_id", "wallet_account_id", name="uq_point_ledger_entries_wallet"
        ),
        sa.UniqueConstraint("operation_id", "reserve_id", name="uq_point_ledger_entries_reserve"),
    )
    # Balances are materialized ONLY by inserting a signed journal effect. No
    # unpaired/edited effects may be committed (deferred validator below).
    op.execute("""
        CREATE FUNCTION fairmount_guard_point_balance() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'point balance rows cannot be removed';
            END IF;
            IF TG_OP = 'INSERT' AND NEW.balance <> 0 THEN
                RAISE EXCEPTION 'point balances must start at zero';
            END IF;
            IF TG_OP = 'UPDATE' AND pg_trigger_depth() <> 2 THEN
                RAISE EXCEPTION 'point balances require a ledger effect';
            END IF;
            RETURN NEW;
        END $$
    """)
    for table in ("account_wallets", "game_reserve"):
        op.execute(f"""
            CREATE TRIGGER tr_guard_{table} BEFORE INSERT OR UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION fairmount_guard_point_balance()
        """)
    op.execute("""
        CREATE FUNCTION fairmount_apply_point_entry() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.wallet_account_id IS NOT NULL THEN
                UPDATE account_wallets SET balance = balance + NEW.delta
                 WHERE account_id = NEW.wallet_account_id;
            ELSE
                UPDATE game_reserve SET balance = balance + NEW.delta WHERE id = NEW.reserve_id;
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER tr_apply_point_entry AFTER INSERT ON point_ledger_entries
        FOR EACH ROW EXECUTE FUNCTION fairmount_apply_point_entry()
    """)
    op.execute("""
        CREATE FUNCTION fairmount_immutable_point_row() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'point history cannot be edited or deleted';
        END $$
    """)
    for table in ("account_wallets", "game_reserve", "point_operations", "point_ledger_entries"):
        op.execute(f"""
            CREATE TRIGGER tr_no_truncate_{table} BEFORE TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION fairmount_immutable_point_row()
        """)
    for table in ("point_operations", "point_ledger_entries"):
        op.execute(f"""
            CREATE TRIGGER tr_immutable_{table} BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION fairmount_immutable_point_row()
        """)
    # A deferred trigger lets a transaction insert an operation before its entries,
    # but refuses commit unless an issuance has one exact credit or a transfer has
    # its full, balanced source debit + destination credit.
    op.execute("""
        CREATE FUNCTION fairmount_validate_point_operation() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            operation point_operations%ROWTYPE;
            entry_count integer;
            debit_count integer;
            credit_count integer;
        BEGIN
            IF TG_TABLE_NAME = 'point_operations' THEN
                SELECT * INTO operation FROM point_operations WHERE id = NEW.id;
            ELSE
                SELECT * INTO operation FROM point_operations WHERE id = NEW.operation_id;
            END IF;
            SELECT count(*),
                   count(*) FILTER (WHERE e.delta = -operation.amount AND
                        ((operation.source_reserve AND e.reserve_id = 1) OR
                         (NOT operation.source_reserve AND
                          e.wallet_account_id = operation.source_wallet_id))),
                   count(*) FILTER (WHERE e.delta = operation.amount AND
                        ((operation.target_reserve AND e.reserve_id = 1) OR
                         (NOT operation.target_reserve AND
                          e.wallet_account_id = operation.target_wallet_id)))
              INTO entry_count, debit_count, credit_count
              FROM point_ledger_entries e WHERE e.operation_id = operation.id;
            IF credit_count <> 1 OR
               (operation.kind = 'OWNER_ISSUE' AND entry_count <> 1) OR
               (operation.kind <> 'OWNER_ISSUE' AND (entry_count <> 2 OR debit_count <> 1))
            THEN
                RAISE EXCEPTION 'incomplete or mismatched point operation %', operation.id;
            END IF;
            RETURN NULL;
        END $$
    """)
    for table in ("point_operations", "point_ledger_entries"):
        op.execute(f"""
            CREATE CONSTRAINT TRIGGER tr_validate_{table}
            AFTER INSERT ON {table} DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION fairmount_validate_point_operation()
        """)


def downgrade() -> None:
    # Never erase the accounting journal for a production downgrade. Empty test
    # databases can round-trip; populated databases must be migrated forward.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM point_operations) THEN
                RAISE EXCEPTION 'refusing to drop populated point journal';
            END IF;
        END $$
    """)
    op.drop_table("point_ledger_entries")
    op.drop_table("point_operations")
    op.execute("DROP TRIGGER tr_account_wallet_create ON accounts")
    op.execute("DROP FUNCTION fairmount_create_account_wallet()")
    op.drop_table("game_reserve")
    op.drop_table("account_wallets")
    op.execute("DROP FUNCTION fairmount_validate_point_operation()")
    op.execute("DROP FUNCTION fairmount_immutable_point_row()")
    op.execute("DROP FUNCTION fairmount_apply_point_entry()")
    op.execute("DROP FUNCTION fairmount_guard_point_balance()")
