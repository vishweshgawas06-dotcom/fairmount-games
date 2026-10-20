"""ORM models. The Alembic migration is the authoritative DDL; a test guards against drift.

Money is always an integer number of virtual points (``BIGINT``), never a float.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from fairmount_api.db.base import Base


def _enum(py_enum: type[enum.Enum], length: int) -> Enum:
    return Enum(
        py_enum,
        native_enum=False,
        length=length,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
        create_constraint=False,
    )


class Role(enum.StrEnum):
    OWNER = "OWNER"
    AGENT = "AGENT"
    PLAYER = "PLAYER"


class RoundState(enum.StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"
    VOID_REFUNDED = "VOID_REFUNDED"


class LedgerType(enum.StrEnum):
    ADMIN_ADJUST = "ADMIN_ADJUST"
    BET_STAKE = "BET_STAKE"
    PAYOUT = "PAYOUT"
    REFUND = "REFUND"


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("role IN ('OWNER','AGENT','PLAYER')", name="role_valid"),
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    role: Mapped[Role] = mapped_column(_enum(Role, 16))
    name: Mapped[str] = mapped_column(String(120))
    mobile: Mapped[str | None] = mapped_column(String(32))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Wallet(Base):
    __tablename__ = "wallets"
    __table_args__ = (CheckConstraint("balance >= 0", name="balance_non_negative"),)

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    balance: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Round(Base):
    __tablename__ = "rounds"
    __table_args__ = (
        CheckConstraint(
            "state IN ('OPEN','CLOSED','SETTLED','VOID_REFUNDED')", name="state_valid"
        ),
        CheckConstraint(
            "winning_number IS NULL OR (winning_number BETWEEN 0 AND 36)",
            name="winning_number_range",
        ),
        CheckConstraint(
            "state <> 'SETTLED' OR winning_number IS NOT NULL", name="settled_has_outcome"
        ),
        CheckConstraint(
            "state <> 'VOID_REFUNDED' OR void_reason IS NOT NULL", name="void_has_reason"
        ),
        CheckConstraint("closes_at > opens_at", name="closes_after_opens"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    state: Mapped[RoundState] = mapped_column(_enum(RoundState, 16), default=RoundState.OPEN)
    opens_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    winning_number: Mapped[int | None] = mapped_column(Integer)
    void_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Bet(Base):
    __tablename__ = "bets"
    __table_args__ = (
        CheckConstraint("amount > 0 AND amount % 5 = 0", name="amount_valid"),
        CheckConstraint("amount <= requested_amount", name="amount_within_request"),
        CheckConstraint("payout IS NULL OR payout >= 0", name="payout_non_negative"),
        Index("ix_bets_round_account", "round_id", "account_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("rounds.id"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    selection_key: Mapped[str] = mapped_column(String(64))
    bet_type: Mapped[str] = mapped_column(String(16))
    requested_amount: Mapped[int] = mapped_column(BigInteger)
    amount: Mapped[int] = mapped_column(BigInteger)
    payout: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class NumberExposure(Base):
    """Per player, per round, per underlying number (straight-up + split exposure)."""

    __tablename__ = "number_exposures"
    __table_args__ = (
        CheckConstraint("number BETWEEN 0 AND 36", name="number_range"),
        CheckConstraint("amount BETWEEN 0 AND 2000", name="amount_within_cap"),
    )

    round_id: Mapped[int] = mapped_column(ForeignKey("rounds.id"), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    amount: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")


class SelectionExposure(Base):
    """Per player, per round, per exact outside / multi-number selection."""

    __tablename__ = "selection_exposures"
    __table_args__ = (CheckConstraint("amount BETWEEN 0 AND 2000", name="amount_within_cap"),)

    round_id: Mapped[int] = mapped_column(ForeignKey("rounds.id"), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    selection_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    amount: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")


class LedgerEntry(Base):
    """Append-only record of every point movement (UPDATE/DELETE are blocked by triggers)."""

    __tablename__ = "ledger_entries"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_ledger_entries_idempotency_key"),
        CheckConstraint(
            "(entry_type = 'BET_STAKE' AND amount < 0)"
            " OR (entry_type IN ('PAYOUT','REFUND') AND amount > 0)"
            " OR (entry_type = 'ADMIN_ADJUST' AND amount <> 0)",
            name="type_matches_sign",
        ),
        CheckConstraint(
            "entry_type <> 'ADMIN_ADJUST' OR (reason IS NOT NULL AND length(trim(reason)) > 0)",
            name="admin_adjust_has_reason",
        ),
        Index("ix_ledger_entries_account", "account_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    entry_type: Mapped[LedgerType] = mapped_column(_enum(LedgerType, 16))
    amount: Mapped[int] = mapped_column(BigInteger)
    round_id: Mapped[int | None] = mapped_column(ForeignKey("rounds.id"))
    bet_id: Mapped[int | None] = mapped_column(ForeignKey("bets.id"))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    reason: Mapped[str | None] = mapped_column(String(500))
    idempotency_key: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class IdempotencyRecord(Base):
    """Stored response for a client-supplied idempotency key (safe retries)."""

    __tablename__ = "idempotency_records"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict[str, Any]] = mapped_column(JSON().with_variant(JSONB(), "postgresql"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
