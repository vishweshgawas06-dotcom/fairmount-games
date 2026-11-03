"""Non-secret idempotency receipts for opt-in owner operator writes."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261103_03"
down_revision = "20261103_02"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "operator_write_receipts",
        sa.Column(
            "owner_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("request_key", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("response", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.CheckConstraint(
            "request_digest ~ '^[0-9a-f]{64}$' AND jsonb_typeof(response) = 'object' "
            "AND NOT (response ? 'secret')",
            name="ck_operator_receipt_no_secret",
        ),
    )
    op.execute("""
        CREATE FUNCTION protect_operator_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'operator receipts are append-only';
        END $$;
        CREATE TRIGGER operator_receipt_immutable
        BEFORE UPDATE OR DELETE OR TRUNCATE ON operator_write_receipts
        FOR EACH STATEMENT EXECUTE FUNCTION protect_operator_receipt();
    """)


def downgrade():
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM operator_write_receipts) THEN
                RAISE EXCEPTION 'refusing to discard operator replay receipts';
            END IF;
        END $$;
    """)
    op.drop_table("operator_write_receipts")
    op.execute("DROP FUNCTION protect_operator_receipt()")
