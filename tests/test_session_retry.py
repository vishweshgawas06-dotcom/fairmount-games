"""Retry/transaction runner behaviour (no PostgreSQL needed: uses in-memory SQLite)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from fairmount_api.core.errors import InvalidStake, TemporaryFailure
from fairmount_api.db.session import make_session_factory, run_in_transaction


class FakePgError(Exception):
    def __init__(self, sqlstate: str):
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


def deadlock() -> OperationalError:
    return OperationalError("stmt", {}, FakePgError("40P01"))


@pytest.fixture
def factory():
    return make_session_factory(create_engine("sqlite://"))


def test_returns_value_on_success(factory):
    assert run_in_transaction(factory, lambda s: 42) == 42


def test_retries_deadlocks_then_succeeds(factory):
    calls = {"n": 0}

    def work(session):
        calls["n"] += 1
        if calls["n"] < 3:
            raise deadlock()
        return "ok"

    assert run_in_transaction(factory, work, sleep=lambda _: None) == "ok"
    assert calls["n"] == 3


def test_gives_up_with_temporary_failure(factory):
    calls = {"n": 0}

    def work(session):
        calls["n"] += 1
        raise deadlock()

    with pytest.raises(TemporaryFailure):
        run_in_transaction(factory, work, attempts=3, sleep=lambda _: None)
    assert calls["n"] == 3


def test_non_retryable_database_errors_propagate_immediately(factory):
    calls = {"n": 0}

    def work(session):
        calls["n"] += 1
        raise OperationalError("stmt", {}, FakePgError("08006"))  # connection failure

    with pytest.raises(OperationalError):
        run_in_transaction(factory, work, sleep=lambda _: None)
    assert calls["n"] == 1


def test_domain_errors_are_never_retried(factory):
    calls = {"n": 0}

    def work(session):
        calls["n"] += 1
        raise InvalidStake()

    with pytest.raises(InvalidStake):
        run_in_transaction(factory, work, sleep=lambda _: None)
    assert calls["n"] == 1
