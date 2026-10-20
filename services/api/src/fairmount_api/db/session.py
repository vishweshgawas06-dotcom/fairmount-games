"""Engine/session factories and a retrying transaction runner."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable

from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from fairmount_api.core.errors import TemporaryFailure

logger = logging.getLogger(__name__)

# PostgreSQL: 40001 serialization_failure, 40P01 deadlock_detected, 55P03 lock_not_available
_RETRYABLE_SQLSTATES = {"40001", "40P01", "55P03"}


def make_engine(url: str, *, echo: bool = False) -> Engine:
    return create_engine(url, echo=echo, pool_pre_ping=True, pool_size=10, max_overflow=10)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def _is_retryable(exc: BaseException) -> bool:
    if not isinstance(exc, DBAPIError):
        return False
    state = getattr(exc.orig, "sqlstate", None)
    return state in _RETRYABLE_SQLSTATES


def run_in_transaction[T](
    factory: sessionmaker[Session],
    work: Callable[[Session], T],
    *,
    attempts: int = 4,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run ``work`` in one transaction; retry on deadlock/serialization failures.

    Expected domain errors (``FairMountError``) are never retried; they propagate and roll back.
    After ``attempts`` retryable failures a :class:`TemporaryFailure` is raised.
    """
    last: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            with factory() as session, session.begin():
                return work(session)
        except DBAPIError as exc:
            if not _is_retryable(exc):
                raise
            last = exc
            logger.warning("retryable database error on attempt %d/%d", attempt, attempts)
            sleep(random.uniform(0.01, 0.05) * attempt)
    raise TemporaryFailure() from last
