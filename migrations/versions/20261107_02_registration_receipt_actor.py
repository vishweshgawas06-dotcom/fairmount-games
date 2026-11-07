"""Preserve existing receipts while allowing role-checked agent registration."""

from alembic import op

revision = "20261107_02"
down_revision = "20261107_01"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "operator_write_receipts", "owner_account_id", new_column_name="actor_account_id"
    )


def downgrade():
    # Old code cannot safely understand agent-owned receipts. Never silently
    # narrow its semantics while those records exist.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM operator_write_receipts r
                JOIN accounts a ON a.id = r.actor_account_id WHERE a.role <> 'OWNER'
            ) THEN
                RAISE EXCEPTION 'refusing to narrow actor receipts with agent history';
            END IF;
        END $$;
    """)
    op.alter_column(
        "operator_write_receipts", "actor_account_id", new_column_name="owner_account_id"
    )
