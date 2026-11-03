"""Bounded gameplay-write attempt windows, pseudonymous and account-independent.

Revision ID: 20261103_01
Revises: 20261025_01

Only HMAC digests are stored: no session token, account ID, IP address or bet
content ever reaches this table. Rows are bounded by distinct digests, not by
request volume, and carry no append-only journal yet because D-02 retention is
still undecided. No write route behavior is enabled by this migration alone.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261103_01"
down_revision: str | None = "20261025_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gameplay_write_buckets",
        sa.Column("key_digest", sa.String(length=64), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint(
            "key_digest COLLATE \"C\" ~ '^[0-9a-f]{64}$'",
            name="ck_gameplay_buckets_key",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_gameplay_buckets_nonnegative"),
        sa.PrimaryKeyConstraint("key_digest"),
    )


def downgrade() -> None:
    # Buckets only throttle live traffic; dropping them resets every window.
    op.drop_table("gameplay_write_buckets")
