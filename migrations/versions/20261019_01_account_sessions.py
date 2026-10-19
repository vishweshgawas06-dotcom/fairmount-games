"""Constrained role-specific session state, without issuing any login sessions.

Revision ID: 20261019_01
Revises: 20261016_08

The app must later enforce DB-time expiry, token possession, disabled status, MFA
step-up, revocations and HTTP/WebSocket authorization before exposing login.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261019_01"
down_revision: str | None = "20261016_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SESSION_LIFETIME_CHECK = """
    last_seen_at >= issued_at AND last_seen_at <= absolute_expires_at
    AND (revoked_at IS NULL OR revoked_at >= issued_at)
    AND (mfa_verified_at IS NULL OR
         (mfa_verified_at >= issued_at AND mfa_verified_at <= last_seen_at))
    AND (
        (role_at_issue = 'OWNER'
         AND absolute_expires_at = issued_at + INTERVAL '8 hours'
         AND idle_expires_at = LEAST(last_seen_at + INTERVAL '15 minutes', absolute_expires_at)
         AND mfa_verified_at IS NOT NULL)
        OR (role_at_issue = 'AGENT'
            AND absolute_expires_at = issued_at + INTERVAL '12 hours'
            AND idle_expires_at = LEAST(last_seen_at + INTERVAL '30 minutes', absolute_expires_at)
            AND mfa_verified_at IS NULL)
        OR (role_at_issue = 'PLAYER'
            AND absolute_expires_at = issued_at + INTERVAL '24 hours'
            AND idle_expires_at = LEAST(last_seen_at + INTERVAL '30 minutes', absolute_expires_at)
            AND mfa_verified_at IS NULL)
    )
"""


def upgrade() -> None:
    op.create_table(
        "account_sessions",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_at_issue", sa.String(length=16), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mfa_verified_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "token_digest COLLATE \"C\" ~ '^[0-9a-f]{64}$'",
            name="ck_account_sessions_token_digest",
        ),
        sa.CheckConstraint(SESSION_LIFETIME_CHECK, name="ck_account_sessions_lifetime"),
        sa.ForeignKeyConstraint(
            ["account_id", "role_at_issue"], ["accounts.id", "accounts.role"],
            name="fk_account_sessions_role", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_digest", name="uq_account_sessions_token_digest"),
    )
    op.create_index(
        "uq_account_sessions_one_active",
        "account_sessions",
        ["account_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_account_sessions_one_active", table_name="account_sessions")
    op.drop_table("account_sessions")
