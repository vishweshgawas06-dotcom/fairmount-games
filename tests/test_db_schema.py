"""Migration and database-level guard tests (real PostgreSQL)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from fairmount_api.db.base import Base
from tests.conftest import alembic_config

pytestmark = pytest.mark.db

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


def _sql(factory, statement: str, **params):
    with factory() as session, session.begin():
        return session.execute(text(statement), params)


def _account(factory) -> int:
    with factory() as session, session.begin():
        aid = session.execute(
            text("INSERT INTO accounts (role, name) VALUES ('PLAYER','P') RETURNING id")
        ).scalar_one()
        session.execute(
            text("INSERT INTO wallets (account_id, balance) VALUES (:a, 100)"), {"a": aid}
        )
    return aid


def _round(factory, state="OPEN", winning=None, reason=None) -> int:
    with factory() as session, session.begin():
        return session.execute(
            text(
                "INSERT INTO rounds (state, opens_at, closes_at, winning_number, void_reason)"
                " VALUES (:s, :o, :c, :w, :r) RETURNING id"
            ),
            {"s": state, "o": NOW, "c": NOW + timedelta(seconds=50), "w": winning, "r": reason},
        ).scalar_one()


def _bet(factory, round_id, account_id, amount=10) -> int:
    with factory() as session, session.begin():
        return session.execute(
            text(
                "INSERT INTO bets (round_id, account_id, selection_key, bet_type,"
                " requested_amount, amount) VALUES (:r, :a, 'red', 'red', :amt, :amt)"
                " RETURNING id"
            ),
            {"r": round_id, "a": account_id, "amt": amount},
        ).scalar_one()


class TestMigrations:
    def test_models_match_migration(self, engine):
        with engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
        assert diff == [], f"models and migration have drifted: {diff}"

    def test_downgrade_then_upgrade_round_trips(self, engine, database_url):
        cfg = alembic_config(database_url)
        command.downgrade(cfg, "base")
        with engine.connect() as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                )
            }
        assert tables <= {"alembic_version"}
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM accounts")).scalar_one() == 0


class TestDatabaseGuards:
    def test_wallet_cannot_go_negative(self, factory):
        aid = _account(factory)
        with pytest.raises(IntegrityError):
            _sql(factory, "UPDATE wallets SET balance = -1 WHERE account_id = :a", a=aid)

    def test_ledger_is_append_only(self, factory):
        aid = _account(factory)
        _sql(
            factory,
            "INSERT INTO ledger_entries (account_id, entry_type, amount, reason, idempotency_key)"
            " VALUES (:a, 'ADMIN_ADJUST', 5, 'seed', 'k1')",
            a=aid,
        )
        with pytest.raises(DBAPIError, match="append-only"):
            _sql(factory, "UPDATE ledger_entries SET amount = 999")
        with pytest.raises(DBAPIError, match="append-only"):
            _sql(factory, "DELETE FROM ledger_entries")

    def test_ledger_idempotency_key_is_unique(self, factory):
        aid = _account(factory)
        insert = (
            "INSERT INTO ledger_entries (account_id, entry_type, amount, reason, idempotency_key)"
            " VALUES (:a, 'ADMIN_ADJUST', 5, 'seed', 'dup')"
        )
        _sql(factory, insert, a=aid)
        with pytest.raises(IntegrityError):
            _sql(factory, insert, a=aid)

    @pytest.mark.parametrize(
        ("entry_type", "amount", "reason"),
        [
            ("BET_STAKE", 10, None),  # stakes must be negative
            ("PAYOUT", -10, None),  # payouts must be positive
            ("REFUND", 0, None),
            ("ADMIN_ADJUST", 0, "x"),
            ("ADMIN_ADJUST", 5, None),  # reason mandatory
            ("ADMIN_ADJUST", 5, "   "),
            ("BOGUS", 5, "x"),
        ],
    )
    def test_ledger_sign_and_reason_rules(self, factory, entry_type, amount, reason):
        aid = _account(factory)
        with pytest.raises(IntegrityError):
            _sql(
                factory,
                "INSERT INTO ledger_entries (account_id, entry_type, amount, reason,"
                " idempotency_key) VALUES (:a, :t, :m, :r, 'k')",
                a=aid,
                t=entry_type,
                m=amount,
                r=reason,
            )

    def test_terminal_round_cannot_change_state(self, factory):
        rid = _round(factory, state="SETTLED", winning=7)
        with pytest.raises(DBAPIError, match="terminal"):
            _sql(factory, "UPDATE rounds SET state = 'OPEN' WHERE id = :i", i=rid)

    def test_void_round_cannot_become_settled(self, factory):
        rid = _round(factory, state="VOID_REFUNDED", reason="test")
        with pytest.raises(DBAPIError):
            _sql(
                factory,
                "UPDATE rounds SET state='SETTLED', winning_number=1 WHERE id = :i",
                i=rid,
            )

    def test_winning_number_is_immutable_once_set(self, factory):
        rid = _round(factory, state="CLOSED", winning=7)
        with pytest.raises(DBAPIError, match="immutable"):
            _sql(factory, "UPDATE rounds SET winning_number = 8 WHERE id = :i", i=rid)

    def test_settled_requires_an_outcome(self, factory):
        with pytest.raises(IntegrityError):
            _round(factory, state="SETTLED", winning=None)

    def test_void_requires_a_reason(self, factory):
        with pytest.raises(IntegrityError):
            _round(factory, state="VOID_REFUNDED", reason=None)

    def test_winning_number_range(self, factory):
        with pytest.raises(IntegrityError):
            _round(factory, state="CLOSED", winning=37)

    def test_rounds_cannot_be_deleted(self, factory):
        rid = _round(factory)
        with pytest.raises(DBAPIError, match="cannot be deleted"):
            _sql(factory, "DELETE FROM rounds WHERE id = :i", i=rid)

    def test_accepted_bets_are_immutable_except_payout(self, factory):
        aid, rid = _account(factory), _round(factory)
        bid = _bet(factory, rid, aid)
        with pytest.raises(DBAPIError, match="immutable"):
            _sql(factory, "UPDATE bets SET amount = 5 WHERE id = :i", i=bid)
        with pytest.raises(DBAPIError, match="immutable"):
            _sql(factory, "UPDATE bets SET selection_key = 'black' WHERE id = :i", i=bid)
        with pytest.raises(DBAPIError, match="cannot be deleted"):
            _sql(factory, "DELETE FROM bets WHERE id = :i", i=bid)
        _sql(factory, "UPDATE bets SET payout = 20 WHERE id = :i", i=bid)  # allowed once
        with pytest.raises(DBAPIError, match="already recorded"):
            _sql(factory, "UPDATE bets SET payout = 30 WHERE id = :i", i=bid)

    @pytest.mark.parametrize("amount", [0, -5, 3, 7])
    def test_bet_amount_must_be_positive_multiple_of_five(self, factory, amount):
        aid, rid = _account(factory), _round(factory)
        with pytest.raises(IntegrityError):
            _bet(factory, rid, aid, amount=amount)

    def test_exposure_cannot_exceed_cap(self, factory):
        aid, rid = _account(factory), _round(factory)
        with pytest.raises(IntegrityError):
            _sql(
                factory,
                "INSERT INTO number_exposures (round_id, account_id, number, amount)"
                " VALUES (:r, :a, 17, 2005)",
                r=rid,
                a=aid,
            )
        with pytest.raises(IntegrityError):
            _sql(
                factory,
                "INSERT INTO selection_exposures (round_id, account_id, selection_key, amount)"
                " VALUES (:r, :a, 'red', 2005)",
                r=rid,
                a=aid,
            )

    def test_account_role_is_validated(self, factory):
        with pytest.raises(IntegrityError):
            _sql(factory, "INSERT INTO accounts (role, name) VALUES ('ROOT','x')")
