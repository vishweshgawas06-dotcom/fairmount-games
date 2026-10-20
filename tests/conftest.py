"""Shared fixtures. DB tests need PostgreSQL: set FAIRMOUNT_TEST_DATABASE_URL.

Locally the DB tests are skipped when the variable is unset. CI sets FAIRMOUNT_REQUIRE_DB=1 so a
missing database is a hard failure rather than a silent skip.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, func, select, text

from fairmount_api.db.models import (
    Bet,
    IdempotencyRecord,
    LedgerEntry,
    NumberExposure,
    Role,
    SelectionExposure,
    Wallet,
)
from fairmount_api.db.session import make_engine, make_session_factory
from fairmount_api.roulette import rounds
from fairmount_api.wallet import service as wallet

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "services" / "api" / "alembic.ini"
TABLES = (
    "idempotency_records, ledger_entries, selection_exposures, number_exposures, "
    "bets, rounds, wallets, accounts"
)


def alembic_config(url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get("FAIRMOUNT_TEST_DATABASE_URL")
    if not url:
        if os.environ.get("FAIRMOUNT_REQUIRE_DB") == "1":
            pytest.fail("FAIRMOUNT_REQUIRE_DB=1 but FAIRMOUNT_TEST_DATABASE_URL is not set")
        pytest.skip("FAIRMOUNT_TEST_DATABASE_URL not set; skipping PostgreSQL tests")
    return url


@pytest.fixture(scope="session")
def engine(database_url: str) -> Engine:
    eng = make_engine(database_url)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    command.upgrade(alembic_config(database_url), "head")
    yield eng
    eng.dispose()


@pytest.fixture
def factory(engine: Engine):
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    return make_session_factory(engine)


@pytest.fixture
def owner_id(factory) -> int:
    return wallet.create_account(factory, role=Role.OWNER, name="Owner")


@pytest.fixture
def make_player(factory, owner_id):
    counter = {"n": 0}

    def _make(balance: int = 0) -> int:
        counter["n"] += 1
        player_id = wallet.create_account(
            factory, role=Role.PLAYER, name=f"Player {counter['n']}", parent_id=owner_id
        )
        if balance:
            wallet.admin_adjust(
                factory,
                actor_id=owner_id,
                account_id=player_id,
                amount=balance,
                reason="test funding",
                idempotency_key=f"fund-{player_id}",
            )
        return player_id

    return _make

# --- helpers shared by DB tests -----------------------------------------------------------
T0 = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)
CUTOFF = T0 + timedelta(seconds=50)
BETTING_NOW = T0 + timedelta(seconds=10)
AFTER_CUTOFF = CUTOFF + timedelta(seconds=1)


def snapshot(factory, account_id: int) -> dict[str, int]:
    """Everything a rejected request must leave untouched, for one account."""

    def count(model) -> int:
        stmt = select(func.count()).select_from(model).where(model.account_id == account_id)
        return s.scalar(stmt)

    with factory() as s:
        return {
            "balance": s.scalar(select(Wallet.balance).where(Wallet.account_id == account_id)),
            "bets": count(Bet),
            "ledger": count(LedgerEntry),
            "number_exposure_rows": count(NumberExposure),
            "selection_exposure_rows": count(SelectionExposure),
            "idempotency_records": count(IdempotencyRecord),
        }


@pytest.fixture
def open_round(factory) -> int:
    return rounds.create_round(factory, opens_at=T0, closes_at=CUTOFF)
