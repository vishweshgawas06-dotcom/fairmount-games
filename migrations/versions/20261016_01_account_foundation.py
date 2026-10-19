"""Account, private identity and agent assignment history foundation.

Revision ID: 20261016_01
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261016_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="ENABLED", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('OWNER', 'AGENT', 'PLAYER')", name="ck_accounts_role"),
        sa.CheckConstraint("status IN ('ENABLED', 'DISABLED')", name="ck_accounts_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_accounts_single_owner",
        "accounts",
        ["role"],
        unique=True,
        postgresql_where=sa.text("role = 'OWNER'"),
    )
    op.create_table(
        "private_identities",
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=True),
        sa.Column("mobile_number", sa.String(length=32), nullable=True),
        sa.Column("login_identifier", sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("account_id"),
    )
    op.create_table(
        "agent_assignments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("player_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "player_account_id <> agent_account_id", name="ck_assignments_not_self"
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at > started_at", name="ck_assignments_valid_interval"
        ),
        sa.ForeignKeyConstraint(["player_account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["agent_account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assignments_agent", "agent_assignments", ["agent_account_id"])
    op.create_index(
        "uq_assignments_current_player",
        "agent_assignments",
        ["player_account_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_assignments_current_player", table_name="agent_assignments")
    op.drop_index("ix_assignments_agent", table_name="agent_assignments")
    op.drop_table("agent_assignments")
    op.drop_table("private_identities")
    op.drop_index("uq_accounts_single_owner", table_name="accounts")
    op.drop_table("accounts")
