"""Canonical namespaced login IDs, without registration or credential behavior.

Revision ID: 20261016_02
Revises: 20261016_01

Legacy non-null login_identifier values must be reviewed/backfilled with a kind before
upgrading; the new CHECK rejects them rather than silently reclassifying identities.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261016_02"
down_revision: str | None = "20261016_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOGIN_IDENTIFIER_CHECK = """
    (login_identifier IS NULL AND login_kind IS NULL)
    OR (
        login_identifier IS NOT NULL AND login_kind IS NOT NULL AND (
            (login_kind = 'PLAYER'
             AND login_identifier COLLATE "C" ~ '^[a-z][a-z0-9_-]{2,31}$'
             AND login_identifier NOT IN ('admin', 'owner', 'support', 'system', 'root')
             AND login_identifier NOT LIKE 'agt-%')
            OR (login_kind = 'AGENT'
                AND login_identifier COLLATE "C" ~ '^agt-[abcdefghjklmnpqrstuvwxyz23456789]{10}$')
        )
    )
"""


def upgrade() -> None:
    op.add_column("private_identities", sa.Column("login_kind", sa.String(length=16)))
    op.create_check_constraint(
        "ck_private_identities_login_format", "private_identities", LOGIN_IDENTIFIER_CHECK
    )
    op.create_index(
        "uq_private_identities_login_namespace",
        "private_identities",
        ["login_kind", "login_identifier"],
        unique=True,
        postgresql_where=sa.text("login_identifier IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_private_identities_login_namespace", table_name="private_identities")
    op.drop_constraint(
        "ck_private_identities_login_format", "private_identities", type_="check"
    )
    op.drop_column("private_identities", "login_kind")
