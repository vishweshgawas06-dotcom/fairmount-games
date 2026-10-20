"""Initial schema: accounts, wallets, rounds, bets, exposures, ledger, idempotency.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("mobile", sa.String(32)),
        sa.Column("parent_id", sa.BigInteger()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_accounts"),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["accounts.id"], name="fk_accounts_parent_id_accounts"
        ),
        sa.CheckConstraint("role IN ('OWNER','AGENT','PLAYER')", name="ck_accounts_role_valid"),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_accounts_name_not_blank"),
    )

    op.create_table(
        "wallets",
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("balance", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("account_id", name="pk_wallets"),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name="fk_wallets_account_id_accounts"
        ),
        sa.CheckConstraint("balance >= 0", name="ck_wallets_balance_non_negative"),
    )

    op.create_table(
        "rounds",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("opens_at", _TS, nullable=False),
        sa.Column("closes_at", _TS, nullable=False),
        sa.Column("winning_number", sa.Integer()),
        sa.Column("void_reason", sa.String(500)),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.Column("settled_at", _TS),
        sa.PrimaryKeyConstraint("id", name="pk_rounds"),
        sa.CheckConstraint(
            "state IN ('OPEN','CLOSED','SETTLED','VOID_REFUNDED')", name="ck_rounds_state_valid"
        ),
        sa.CheckConstraint(
            "winning_number IS NULL OR (winning_number BETWEEN 0 AND 36)",
            name="ck_rounds_winning_number_range",
        ),
        sa.CheckConstraint(
            "state <> 'SETTLED' OR winning_number IS NOT NULL", name="ck_rounds_settled_has_outcome"
        ),
        sa.CheckConstraint(
            "state <> 'VOID_REFUNDED' OR void_reason IS NOT NULL", name="ck_rounds_void_has_reason"
        ),
        sa.CheckConstraint("closes_at > opens_at", name="ck_rounds_closes_after_opens"),
    )

    op.create_table(
        "bets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("round_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("selection_key", sa.String(64), nullable=False),
        sa.Column("bet_type", sa.String(16), nullable=False),
        sa.Column("requested_amount", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("payout", sa.BigInteger()),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_bets"),
        sa.ForeignKeyConstraint(["round_id"], ["rounds.id"], name="fk_bets_round_id_rounds"),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name="fk_bets_account_id_accounts"
        ),
        sa.CheckConstraint("amount > 0 AND amount % 5 = 0", name="ck_bets_amount_valid"),
        sa.CheckConstraint("amount <= requested_amount", name="ck_bets_amount_within_request"),
        sa.CheckConstraint("payout IS NULL OR payout >= 0", name="ck_bets_payout_non_negative"),
    )
    op.create_index("ix_bets_round_account", "bets", ["round_id", "account_id"])

    op.create_table(
        "number_exposures",
        sa.Column("round_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("round_id", "account_id", "number", name="pk_number_exposures"),
        sa.ForeignKeyConstraint(
            ["round_id"], ["rounds.id"], name="fk_number_exposures_round_id_rounds"
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name="fk_number_exposures_account_id_accounts"
        ),
        sa.CheckConstraint("number BETWEEN 0 AND 36", name="ck_number_exposures_number_range"),
        sa.CheckConstraint(
            "amount BETWEEN 0 AND 2000", name="ck_number_exposures_amount_within_cap"
        ),
    )

    op.create_table(
        "selection_exposures",
        sa.Column("round_id", sa.BigInteger(), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("selection_key", sa.String(64), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint(
            "round_id", "account_id", "selection_key", name="pk_selection_exposures"
        ),
        sa.ForeignKeyConstraint(
            ["round_id"], ["rounds.id"], name="fk_selection_exposures_round_id_rounds"
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name="fk_selection_exposures_account_id_accounts"
        ),
        sa.CheckConstraint(
            "amount BETWEEN 0 AND 2000", name="ck_selection_exposures_amount_within_cap"
        ),
    )

    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("entry_type", sa.String(16), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("round_id", sa.BigInteger()),
        sa.Column("bet_id", sa.BigInteger()),
        sa.Column("actor_id", sa.BigInteger()),
        sa.Column("reason", sa.String(500)),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_ledger_entries"),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name="fk_ledger_entries_account_id_accounts"
        ),
        sa.ForeignKeyConstraint(
            ["round_id"], ["rounds.id"], name="fk_ledger_entries_round_id_rounds"
        ),
        sa.ForeignKeyConstraint(["bet_id"], ["bets.id"], name="fk_ledger_entries_bet_id_bets"),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["accounts.id"], name="fk_ledger_entries_actor_id_accounts"
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_ledger_entries_idempotency_key"),
        sa.CheckConstraint(
            "(entry_type = 'BET_STAKE' AND amount < 0)"
            " OR (entry_type IN ('PAYOUT','REFUND') AND amount > 0)"
            " OR (entry_type = 'ADMIN_ADJUST' AND amount <> 0)",
            name="ck_ledger_entries_type_matches_sign",
        ),
        sa.CheckConstraint(
            "entry_type <> 'ADMIN_ADJUST' OR (reason IS NOT NULL AND length(trim(reason)) > 0)",
            name="ck_ledger_entries_admin_adjust_has_reason",
        ),
    )
    op.create_index("ix_ledger_entries_account", "ledger_entries", ["account_id"])

    op.create_table(
        "idempotency_records",
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("account_id", "key", name="pk_idempotency_records"),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name="fk_idempotency_records_account_id_accounts"
        ),
    )

    # --- Database-level safety nets (independent of application code) -----------------------
    op.execute(
        """
        CREATE FUNCTION fm_block_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% on % is not allowed (append-only)', TG_OP, TG_TABLE_NAME
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER ledger_entries_append_only
        BEFORE UPDATE OR DELETE ON ledger_entries
        FOR EACH ROW EXECUTE FUNCTION fm_block_mutation();
        """
    )
    op.execute(
        """
        CREATE FUNCTION fm_rounds_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'rounds cannot be deleted'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.state IN ('SETTLED','VOID_REFUNDED') AND NEW.state <> OLD.state THEN
                RAISE EXCEPTION 'round % is terminal (%)', OLD.id, OLD.state
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.winning_number IS NOT NULL
               AND NEW.winning_number IS DISTINCT FROM OLD.winning_number THEN
                RAISE EXCEPTION 'winning_number of round % is immutable once persisted', OLD.id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER rounds_guard
        BEFORE UPDATE OR DELETE ON rounds
        FOR EACH ROW EXECUTE FUNCTION fm_rounds_guard();
        """
    )
    op.execute(
        """
        CREATE FUNCTION fm_bets_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'accepted bets are immutable and cannot be deleted'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF (NEW.round_id, NEW.account_id, NEW.selection_key, NEW.bet_type,
                NEW.requested_amount, NEW.amount)
               IS DISTINCT FROM
               (OLD.round_id, OLD.account_id, OLD.selection_key, OLD.bet_type,
                OLD.requested_amount, OLD.amount) THEN
                RAISE EXCEPTION 'accepted bets are immutable (only payout may be set)'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF OLD.payout IS NOT NULL AND NEW.payout IS DISTINCT FROM OLD.payout THEN
                RAISE EXCEPTION 'bet payout is already recorded'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER bets_guard
        BEFORE UPDATE OR DELETE ON bets
        FOR EACH ROW EXECUTE FUNCTION fm_bets_guard();
        """
    )


def downgrade() -> None:
    for trigger, table in (
        ("bets_guard", "bets"),
        ("rounds_guard", "rounds"),
        ("ledger_entries_append_only", "ledger_entries"),
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
    for fn in ("fm_bets_guard", "fm_rounds_guard", "fm_block_mutation"):
        op.execute(f"DROP FUNCTION IF EXISTS {fn}()")
    for table in (
        "idempotency_records",
        "ledger_entries",
        "selection_exposures",
        "number_exposures",
        "bets",
        "rounds",
        "wallets",
        "accounts",
    ):
        op.drop_table(table)
