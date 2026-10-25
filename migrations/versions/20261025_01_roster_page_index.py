"""Index active agent assignments for bounded UUID-keyset roster reads.

Revision ID: 20261025_01
Revises: 20261023_03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261025_01"
down_revision: str | None = "20261023_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_assignments_agent_current_player",
        "agent_assignments",
        ["agent_account_id", "player_account_id"],
        postgresql_where=sa.text("ended_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_assignments_agent_current_player", table_name="agent_assignments")
