"""Global UUID roulette round, immutable accepted-bet rows and stake linkage.

Revision ID: 20261023_02
Revises: 20261023_01
No live bet admission, settlement or recovery service is enabled by this migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261023_02"
down_revision: str | None = "20261023_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROUND_STRUCTURE_CHECK = """
    closes_at = opens_at + INTERVAL '50 seconds'
    AND reveal_at = opens_at + INTERVAL '60 seconds'
    AND state IN ('OPEN', 'CLOSED', 'SETTLED', 'VOID_REFUNDED')
    AND ((winning_number IS NULL AND result_set_at IS NULL)
         OR (winning_number BETWEEN 0 AND 36 AND result_set_at IS NOT NULL
             AND result_set_at >= closes_at))
    AND (state NOT IN ('CLOSED', 'SETTLED') OR winning_number IS NOT NULL)
    AND (state <> 'OPEN' OR winning_number IS NULL)
"""


def upgrade() -> None:
    op.create_table(
        "roulette_rounds",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("state", sa.String(16), server_default=sa.text("'OPEN'"), nullable=False),
        sa.Column("opens_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reveal_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("winning_number", sa.SmallInteger()),
        sa.Column("result_set_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(ROUND_STRUCTURE_CHECK, name="ck_roulette_rounds_structure"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_roulette_rounds_one_open",
        "roulette_rounds",
        ["state"],
        unique=True,
        postgresql_where=sa.text("state = 'OPEN'"),
    )
    op.create_table(
        "roulette_bets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("round_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("player_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("player_role", sa.String(16), server_default=sa.text("'PLAYER'"), nullable=False),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("selection_key", sa.String(64), nullable=False),
        sa.Column("accepted_stake", sa.BigInteger(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "player_role = 'PLAYER' AND accepted_stake >= 5 "
            "AND accepted_stake % 5 = 0 AND length(selection_key) > 0",
            name="ck_roulette_bets_shape",
        ),
        sa.ForeignKeyConstraint(["round_id"], ["roulette_rounds.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["player_account_id"], ["account_wallets.account_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["player_account_id", "player_role"],
            ["accounts.id", "accounts.role"],
            name="fk_roulette_bets_player_role",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["operation_id"], ["point_operations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("operation_id", name="uq_roulette_bets_operation"),
    )
    op.create_index(
        "ix_roulette_bets_round_player", "roulette_bets", ["round_id", "player_account_id"]
    )
    op.execute("""
        CREATE FUNCTION fairmount_guard_round() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' OR TG_OP = 'TRUNCATE' THEN
                RAISE EXCEPTION 'round history cannot be removed';
            END IF;
            IF OLD.id IS DISTINCT FROM NEW.id OR
               OLD.opens_at IS DISTINCT FROM NEW.opens_at OR
               OLD.closes_at IS DISTINCT FROM NEW.closes_at OR
               OLD.reveal_at IS DISTINCT FROM NEW.reveal_at OR
               (OLD.winning_number IS NOT NULL AND
                OLD.winning_number IS DISTINCT FROM NEW.winning_number) OR
               (OLD.result_set_at IS NOT NULL AND
                OLD.result_set_at IS DISTINCT FROM NEW.result_set_at) OR
               (OLD.state = 'CLOSED' AND NEW.state NOT IN ('CLOSED','SETTLED','VOID_REFUNDED')) OR
               (OLD.state = 'OPEN' AND NEW.state NOT IN ('OPEN','CLOSED','VOID_REFUNDED')) OR
               (OLD.state IN ('SETTLED','VOID_REFUNDED') AND NEW.state <> OLD.state)
            THEN
                RAISE EXCEPTION 'invalid round transition or outcome rewrite';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER tr_round_guard BEFORE UPDATE OR DELETE ON roulette_rounds
        FOR EACH ROW EXECUTE FUNCTION fairmount_guard_round()
    """)
    op.execute("""
        CREATE TRIGGER tr_round_no_truncate BEFORE TRUNCATE ON roulette_rounds
        FOR EACH STATEMENT EXECUTE FUNCTION fairmount_guard_round()
    """)
    op.execute("""
        CREATE FUNCTION fairmount_bet_before_insert() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE current_round roulette_rounds%ROWTYPE;
        BEGIN
            -- Locks the round until commit so closing cannot race a bet's cutoff.
            SELECT * INTO current_round FROM roulette_rounds WHERE id = NEW.round_id FOR UPDATE;
            NEW.accepted_at := clock_timestamp();
            IF current_round.id IS NULL OR current_round.state <> 'OPEN' OR
               NEW.accepted_at < current_round.opens_at OR
               NEW.accepted_at >= current_round.closes_at THEN
                RAISE EXCEPTION 'betting is closed for this round';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER tr_bet_cutoff BEFORE INSERT ON roulette_bets
        FOR EACH ROW EXECUTE FUNCTION fairmount_bet_before_insert()
    """)
    op.execute("""
        CREATE FUNCTION fairmount_guard_accepted_bet() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'accepted bets are immutable';
        END $$
    """)
    op.execute("""
        CREATE TRIGGER tr_bet_immutable BEFORE UPDATE OR DELETE ON roulette_bets
        FOR EACH ROW EXECUTE FUNCTION fairmount_guard_accepted_bet()
    """)
    op.execute("""
        CREATE TRIGGER tr_bet_no_truncate BEFORE TRUNCATE ON roulette_bets
        FOR EACH STATEMENT EXECUTE FUNCTION fairmount_guard_accepted_bet()
    """)
    op.execute("""
        CREATE FUNCTION fairmount_validate_bet_stake() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            operation point_operations%ROWTYPE;
            accepted roulette_bets%ROWTYPE;
            operation_key uuid;
        BEGIN
            IF TG_TABLE_NAME = 'point_operations' THEN
                IF NEW.kind <> 'BET_STAKE' THEN RETURN NULL; END IF;
                operation_key := NEW.id;
            ELSE
                operation_key := NEW.operation_id;
            END IF;
            SELECT * INTO operation FROM point_operations WHERE id = operation_key;
            SELECT * INTO accepted FROM roulette_bets WHERE operation_id = operation_key;
            IF operation.kind <> 'BET_STAKE' OR accepted.id IS NULL OR
               operation.context_id IS DISTINCT FROM accepted.id OR
               operation.source_wallet_id IS DISTINCT FROM accepted.player_account_id OR
               operation.amount IS DISTINCT FROM accepted.accepted_stake THEN
                RAISE EXCEPTION 'accepted bet and reserved stake must match';
            END IF;
            RETURN NULL;
        END $$
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER tr_stake_has_bet
        AFTER INSERT ON point_operations DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION fairmount_validate_bet_stake()
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER tr_bet_has_stake
        AFTER INSERT ON roulette_bets DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION fairmount_validate_bet_stake()
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM roulette_rounds) OR
               EXISTS (SELECT 1 FROM roulette_bets) THEN
                RAISE EXCEPTION 'refusing to drop populated round/bet history';
            END IF;
        END $$
    """)
    op.execute("DROP TRIGGER tr_stake_has_bet ON point_operations")
    op.drop_index("ix_roulette_bets_round_player", table_name="roulette_bets")
    op.drop_table("roulette_bets")
    op.drop_index("uq_roulette_rounds_one_open", table_name="roulette_rounds")
    op.drop_table("roulette_rounds")
    op.execute("DROP FUNCTION fairmount_validate_bet_stake()")
    op.execute("DROP FUNCTION fairmount_guard_accepted_bet()")
    op.execute("DROP FUNCTION fairmount_bet_before_insert()")
    op.execute("DROP FUNCTION fairmount_guard_round()")
