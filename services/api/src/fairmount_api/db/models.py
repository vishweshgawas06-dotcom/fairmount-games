"""Account, private identity, assignment and canonical login-ID schema.

These models do not authenticate users, authorize transfers, or resolve identifier reuse
and retention after eligible anonymization. Credential, MFA and session rows alone never
grant access.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Metadata shared by the first Alembic migration."""


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'ENABLED'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("role IN ('OWNER', 'AGENT', 'PLAYER')", name="ck_accounts_role"),
        CheckConstraint("status IN ('ENABLED', 'DISABLED')", name="ck_accounts_status"),
        UniqueConstraint("id", "role", name="uq_accounts_id_role"),
        Index(
            "uq_accounts_single_owner", "role", unique=True, postgresql_where=text("role = 'OWNER'")
        ),
    )


# Keep this DB check in sync with the P03-T01b migration and pure identifier helpers.
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


class PrivateIdentity(Base):
    __tablename__ = "private_identities"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), primary_key=True
    )
    display_name: Mapped[str | None] = mapped_column(String(160))
    mobile_number: Mapped[str | None] = mapped_column(String(32))
    login_identifier: Mapped[str | None] = mapped_column(String(128))
    login_kind: Mapped[str | None] = mapped_column(String(16))

    __table_args__ = (
        # MATCH SIMPLE skips this FK when login_kind is NULL; the original account_id
        # FK still requires a parent account for those identity rows.
        ForeignKeyConstraint(
            ["account_id", "login_kind"],
            ["accounts.id", "accounts.role"],
            name="fk_private_identities_login_role",
            ondelete="RESTRICT",
        ),
        CheckConstraint(LOGIN_IDENTIFIER_CHECK, name="ck_private_identities_login_format"),
        Index(
            "uq_private_identities_login_namespace",
            "login_kind",
            "login_identifier",
            unique=True,
            postgresql_where=text("login_identifier IS NOT NULL"),
        ),
    )


# The check guards structural states, not expiry at request time or proof of secret possession.
# The transition to a password needs an authenticated, atomic future service and audit.
CREDENTIAL_STATE_CHECK = """
    (password_hash IS NULL AND password_changed_at IS NULL
     AND initial_secret_digest IS NOT NULL
     AND initial_secret_digest COLLATE "C" ~ '^[0-9a-f]{64}$'
     AND initial_secret_expires_at IS NOT NULL
     AND initial_secret_expires_at = initial_secret_issued_at + INTERVAL '24 hours'
     AND initial_secret_consumed_at IS NULL)
    OR
    (password_hash IS NOT NULL AND password_changed_at IS NOT NULL
     AND password_hash LIKE '$argon2id$%'
     AND initial_secret_digest IS NULL AND initial_secret_expires_at IS NULL
     AND initial_secret_consumed_at IS NOT NULL
     AND initial_secret_consumed_at >= initial_secret_issued_at
     AND password_changed_at >= initial_secret_consumed_at)
"""


class AccountCredential(Base):
    __tablename__ = "account_credentials"

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), primary_key=True
    )
    initial_secret_digest: Mapped[str | None] = mapped_column(String(64))
    initial_secret_issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    initial_secret_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    initial_secret_consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_hash: Mapped[str | None] = mapped_column(Text)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(CREDENTIAL_STATE_CHECK, name="ck_account_credentials_state"),
    )


class OwnerMFA(Base):
    __tablename__ = "owner_mfa"

    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    account_role: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'OWNER'")
    )
    key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    nonce: Mapped[str] = mapped_column(String(16), nullable=False)
    ciphertext: Mapped[str] = mapped_column(String(64), nullable=False)
    last_accepted_step: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["account_id", "account_role"],
            ["accounts.id", "accounts.role"],
            name="fk_owner_mfa_role",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "account_role = 'OWNER' AND key_version > 0 "
            "AND nonce COLLATE \"C\" ~ '^[A-Za-z0-9_-]{16}$' "
            "AND ciphertext COLLATE \"C\" ~ '^[A-Za-z0-9_-]{64}$' "
            "AND (last_accepted_step IS NULL OR last_accepted_step >= 0) "
            "AND (confirmed_at IS NULL OR confirmed_at >= created_at) "
            "AND (confirmed_at IS NOT NULL OR last_accepted_step IS NULL)",
            name="ck_owner_mfa_structure",
        ),
    )


class OwnerRecoveryCode(Base):
    __tablename__ = "owner_recovery_codes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("owner_mfa.account_id", ondelete="RESTRICT"), nullable=False
    )
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "digest COLLATE \"C\" ~ '^[0-9a-f]{64}$' "
            "AND (consumed_at IS NULL OR consumed_at >= issued_at)",
            name="ck_owner_recovery_code_structure",
        ),
        UniqueConstraint("owner_account_id", "digest", name="uq_owner_recovery_code_digest"),
    )


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


class AccountSession(Base):
    __tablename__ = "account_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    role_at_issue: Mapped[str] = mapped_column(String(16), nullable=False)
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    mfa_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["account_id", "role_at_issue"],
            ["accounts.id", "accounts.role"],
            name="fk_account_sessions_role",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "token_digest COLLATE \"C\" ~ '^[0-9a-f]{64}$'",
            name="ck_account_sessions_token_digest",
        ),
        CheckConstraint(SESSION_LIFETIME_CHECK, name="ck_account_sessions_lifetime"),
        UniqueConstraint("token_digest", name="uq_account_sessions_token_digest"),
        Index(
            "uq_account_sessions_one_active",
            "account_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )


SECURITY_EVENT_CHECK = """
    event_type IN (
        'OWNER_BOOTSTRAP_ISSUED', 'OWNER_BOOTSTRAP_REISSUED',
        'INITIAL_CREDENTIAL_ISSUED', 'INITIAL_CREDENTIAL_CONSUMED',
        'PASSWORD_CHANGED', 'OWNER_MFA_ENROLLED', 'OWNER_MFA_VERIFIED',
        'OWNER_SESSION_STARTED', 'SESSION_REVOKED'
    ) AND source IN ('LOCAL_CLI', 'DASHBOARD', 'SELF_SERVICE')
    AND (actor_account_id IS NOT NULL OR
         (source = 'LOCAL_CLI' AND event_type IN
          ('OWNER_BOOTSTRAP_ISSUED', 'OWNER_BOOTSTRAP_REISSUED')))
"""


class SecurityEvent(Base):
    __tablename__ = "security_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT")
    )
    target_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint(SECURITY_EVENT_CHECK, name="ck_security_events_valid"),
        Index("ix_security_events_target_time", "target_account_id", "occurred_at"),
    )


class AgentAssignment(Base):
    __tablename__ = "agent_assignments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    player_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    agent_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    actor_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "player_account_id <> agent_account_id", name="ck_assignments_not_self"
        ),
        CheckConstraint(
            "ended_at IS NULL OR ended_at > started_at", name="ck_assignments_valid_interval"
        ),
        Index(
            "uq_assignments_current_player",
            "player_account_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
        Index("ix_assignments_agent", "agent_account_id"),
    )
