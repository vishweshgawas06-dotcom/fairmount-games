"""Bind non-null login kinds to account roles without adding registration APIs.

Revision ID: 20261016_03
Revises: 20261016_02

The FK validates existing rows. Mismatched legacy identities cause an atomic migration
failure and require explicit review/backfill; this revision never reclassifies them.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261016_03"
down_revision: str | None = "20261016_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PostgreSQL requires a unique referenced key for the composite foreign key.
    op.create_unique_constraint("uq_accounts_id_role", "accounts", ["id", "role"])
    op.create_foreign_key(
        "fk_private_identities_login_role",
        "private_identities",
        "accounts",
        ["account_id", "login_kind"],
        ["id", "role"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_private_identities_login_role", "private_identities", type_="foreignkey")
    op.drop_constraint("uq_accounts_id_role", "accounts", type_="unique")
