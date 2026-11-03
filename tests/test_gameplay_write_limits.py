"""PostgreSQL gameplay-write attempt windows: serialization, reset and pseudonymity."""

import os
import secrets
import threading
import unittest
from datetime import timedelta
from unittest.mock import patch

from fairmount_api.db.models import GameplayWriteBucket
from fairmount_api.roulette.admission import BetUnavailable
from fairmount_api.roulette.write_limits import (
    SESSION_LIMIT,
    SOURCE_LIMIT,
    _session_digest,
    _source_digest,
    guard_gameplay_write,
)
from sqlalchemy import create_engine, func, select, text, update

from infrastructure.local_db_url import local_database_url

PEPPER = b"test-only-gameplay-write-pepper-32b!"
SOURCE = "203.0.113.7"


class _Denied(Exception):
    pass


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class GameplayWriteLimitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_engine(local_database_url(test=True))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        self.token = secrets.token_urlsafe(32)
        self.source = f"203.0.113.{secrets.randbelow(200) + 20}"

    def tearDown(self) -> None:
        self.transaction.rollback()
        self.connection.close()

    def keys(self, token=None, source=None):
        """The two pseudonymous keys this test's traffic owns."""
        return (
            _session_digest(token or self.token, PEPPER),
            _source_digest(source or self.source, PEPPER),
        )

    def attempt(self, token=None, source=None, write=None, denied=(BetUnavailable,)):
        return guard_gameplay_write(
            self.connection,
            token or self.token,
            source_ip=source or self.source,
            pepper=PEPPER,
            write=write or (lambda _connection: "accepted"),
            denied_by=denied,
        )

    def source_attempts(self):
        return self.connection.scalar(
            select(GameplayWriteBucket.attempts).where(
                GameplayWriteBucket.key_digest == _source_digest(self.source, PEPPER)
            )
        )

    def buckets(self, token=None, source=None):
        """Only this test's rows: other modules share the disposable database."""
        return self.connection.execute(
            select(GameplayWriteBucket.key_digest, GameplayWriteBucket.attempts)
            .where(GameplayWriteBucket.key_digest.in_(self.keys(token, source)))
            .order_by(GameplayWriteBucket.key_digest)
        ).all()

    def test_attempts_are_counted_then_throttled_with_a_retry_hint(self):
        with patch("fairmount_api.roulette.write_limits.SESSION_LIMIT", 3):
            results = [self.attempt() for _ in range(4)]
        self.assertEqual([r.allowed for r in results], [True, True, True, False])
        self.assertEqual([r.throttled for r in results], [False, False, False, True])
        self.assertGreaterEqual(results[-1].retry_after, 1)
        self.assertLessEqual(results[-1].retry_after, 61)
        self.assertEqual(sorted(row.attempts for row in self.buckets()), [3, 3])

    def test_window_expiry_reopens_the_bucket(self):
        with patch("fairmount_api.roulette.write_limits.SESSION_LIMIT", 1):
            self.assertTrue(self.attempt().allowed)
            self.assertTrue(self.attempt().throttled)
            self.connection.execute(
                update(GameplayWriteBucket.__table__)
                .where(GameplayWriteBucket.key_digest.in_(self.keys()))
                .values(window_started_at=func.clock_timestamp() - timedelta(minutes=2))
            )
            self.assertTrue(self.attempt().allowed)
        self.assertEqual([row.attempts for row in self.buckets()], [1, 1])

    def test_source_window_spans_sessions(self):
        tokens = [secrets.token_urlsafe(32) for _ in range(4)]
        with patch("fairmount_api.roulette.write_limits.SESSION_LIMIT", 2), patch(
            "fairmount_api.roulette.write_limits.SOURCE_LIMIT", 3
        ):
            # Fresh sessions, so only the shared source quota can bind.
            allowed = [self.attempt(token=token).allowed for token in tokens]
        self.assertEqual(allowed, [True, True, True, False])
        # The throttled fourth attempt spends no budget and creates no row.
        self.assertEqual(self.source_attempts(), 3)

    def test_a_crowded_source_does_not_block_another_source(self):
        other = "198.51.100.9"
        first, second, third, elsewhere = (secrets.token_urlsafe(32) for _ in range(4))
        with patch("fairmount_api.roulette.write_limits.SESSION_LIMIT", 1), patch(
            "fairmount_api.roulette.write_limits.SOURCE_LIMIT", 2
        ):
            self.assertTrue(self.attempt(token=first).allowed)
            self.assertTrue(self.attempt(token=second).allowed)
            self.assertTrue(self.attempt(token=third).throttled)  # source exhausted
            self.assertTrue(self.attempt(token=elsewhere, source=other).allowed)

    def test_expected_denial_counts_but_rolls_back_its_effects(self):
        def write(connection):
            connection.execute(text("SELECT 1"))  # a side effect inside the savepoint
            raise BetUnavailable("Bet unavailable")

        outcome = self.attempt(write=write)
        self.assertFalse(outcome.allowed)
        self.assertFalse(outcome.throttled)
        self.assertIs(outcome.denial, BetUnavailable)
        self.assertEqual([row.attempts for row in self.buckets()], [1, 1])

    def test_unexpected_database_errors_are_not_reported_as_denials(self):
        def write(connection):
            raise RuntimeError("connection lost")

        with self.assertRaises(RuntimeError):
            self.attempt(write=write)
        # The increment shares the failing outer transaction, so a rollback
        # (what the route does on an unexpected error) discards it entirely.
        self.transaction.rollback()
        self.transaction = self.connection.begin()
        self.assertEqual(self.buckets(), [])

    def test_invalid_context_fails_closed(self):
        cases = (
            {"pepper": b"short"},
            {"pepper": "not-bytes"},
            {"raw_token": "not-a-token"},
            {"raw_token": None},
            {"source_ip": "999.1.1.1"},
            {"source_ip": None},
            {"write": None},
            {"denied_by": ()},
            {"denied_by": (object(),)},
        )
        base = {
            "raw_token": self.token,
            "source_ip": SOURCE,
            "pepper": PEPPER,
            "write": lambda _connection: "accepted",
            "denied_by": (BetUnavailable,),
        }
        for change in cases:
            inputs = {**base, **change}
            with self.subTest(change=list(change)), self.assertRaises(ValueError):
                guard_gameplay_write(
                    self.connection,
                    inputs["raw_token"],
                    source_ip=inputs["source_ip"],
                    pepper=inputs["pepper"],
                    write=inputs["write"],
                    denied_by=inputs["denied_by"],
                )

    def test_only_keyed_digests_are_persisted(self):
        with patch("fairmount_api.roulette.write_limits.SESSION_LIMIT", 2):
            self.attempt()
            self.attempt()
            self.attempt()
        rows = self.buckets()
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertRegex(row.key_digest, r"^[0-9a-f]{64}$")
            self.assertNotIn(self.token, row.key_digest)
            self.assertNotIn(SOURCE, row.key_digest)
        stored = " ".join(row.key_digest for row in rows)
        self.assertNotIn(self.token, stored)
        self.assertNotIn(self.source, stored)

    def test_default_limits_match_the_documented_budget(self):
        self.assertGreaterEqual(SESSION_LIMIT, 1)
        self.assertGreater(SOURCE_LIMIT, SESSION_LIMIT)


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class GameplayWriteLimitConcurrencyTests(unittest.TestCase):
    """Independent connections must serialise on the bucket row, not overrun it."""

    def test_concurrent_attempts_never_exceed_the_limit(self):
        engine = create_engine(local_database_url(test=True))
        token = secrets.token_urlsafe(32)
        source = f"198.51.100.{secrets.randbelow(200) + 20}"
        allowed: list[bool] = []
        lock = threading.Lock()
        barrier = threading.Barrier(8)

        def worker():
            connection = engine.connect()
            try:
                connection.begin()
                barrier.wait(timeout=10)
                outcome = guard_gameplay_write(
                    connection,
                    token,
                    source_ip=source,
                    pepper=PEPPER,
                    write=lambda _connection: "accepted",
                    denied_by=(BetUnavailable,),
                )
                connection.commit()
                with lock:
                    allowed.append(outcome.allowed)
            finally:
                connection.close()

        try:
            with patch("fairmount_api.roulette.write_limits.SESSION_LIMIT", 3):
                threads = [threading.Thread(target=worker) for _ in range(8)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=30)
            self.assertEqual(len(allowed), 8)
            self.assertEqual(allowed.count(True), 3)
            with engine.connect() as connection:
                attempts = connection.scalar(
                    select(GameplayWriteBucket.attempts).where(
                        GameplayWriteBucket.key_digest
                        == _session_digest(token, PEPPER)
                    )
                )
            self.assertEqual(attempts, 3)
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
