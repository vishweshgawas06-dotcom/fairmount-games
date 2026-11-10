"""Bounded administrative history keyset indexes; no gameplay export."""

import sqlalchemy as sa
from alembic import op

revision = "20261107_03"
down_revision = "20261107_02"
branch_labels = None
depends_on = None

_PREDICATE = sa.text(
    "kind IN ('OWNER_ISSUE','OWNER_TRANSFER','AGENT_TRANSFER','RESERVE_FUND',"
    "'RESERVE_WITHDRAW','AGENT_DISABLE_RETURN')"
)


def upgrade():
    op.create_index(
        "ix_point_operations_admin_page",
        "point_operations",
        ["created_at", "id"],
        postgresql_where=_PREDICATE,
    )
    op.create_index(
        "ix_point_operations_actor_admin_page",
        "point_operations",
        ["actor_account_id", "created_at", "id"],
        postgresql_where=_PREDICATE,
    )


def downgrade():
    op.drop_index("ix_point_operations_actor_admin_page", table_name="point_operations")
    op.drop_index("ix_point_operations_admin_page", table_name="point_operations")
