"""PostgreSQL-only pseudonymous failure auditing and admission windows."""

import os
import unittest

from fairmount_api.db.models import AuthAttemptBucket, AuthFailureEvent
from fairmount_api.identity.auth_attempts import guarded_authentication
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.exc import DBAPIError

from infrastructure.local_db_url import local_database_url

_TEST_SECRET = b"test-only-auth-pepper-not-for-deployment!"


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class AuthAttemptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_engine(local_database_url(test=True))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()

    def tearDown(self) -> None:
        self.transaction.rollback()
        self.connection.close()

    def attempt(self, identifier="missing-player", ip="203.0.113.11", callback=None):
        if callback is None:

            def callback(conn):
                raise ValueError("generic authentication denial")

        return guarded_authentication(
            self.connection,
            surface="MEMBER_LOGIN",
            identifier=identifier,
            source_ip=ip,
            pepper=_TEST_SECRET,
            authenticate=callback,
            denied_by=(ValueError,),
        )

    def test_five_failed_proofs_block_same_subject_across_sources_without_raw_data(self):
        for _ in range(5):
            denied = self.attempt()
            self.assertFalse(denied.allowed)
            self.assertFalse(denied.throttled)
        calls = []
        blocked = self.attempt(ip="2001:db8::11", callback=lambda _: calls.append(True))
        self.assertTrue(blocked.throttled)
        self.assertFalse(calls)
        # Unknown labels are guarded identically; no database account is needed.
        self.assertEqual(
            self.connection.scalar(select(func.count()).select_from(AuthFailureEvent)), 6
        )
        events = self.connection.execute(
            select(
                AuthFailureEvent.subject_digest,
                AuthFailureEvent.source_digest,
                AuthFailureEvent.outcome,
            )
        ).all()
        self.assertEqual({row.outcome for row in events}, {"FAILED", "THROTTLED"})
        self.assertEqual(len({row.subject_digest for row in events}), 1)
        self.assertEqual(len({row.source_digest for row in events}), 2)
        self.assertTrue(all(len(row.subject_digest) == 64 for row in events))
        self.assertEqual(
            self.connection.scalar(select(func.count()).select_from(AuthAttemptBucket)), 3
        )
        self.assertNotIn("missing-player", repr(events))
        with self.assertRaises(DBAPIError), self.connection.begin_nested():
            self.connection.execute(update(AuthFailureEvent.__table__).values(outcome="FAILED"))

    def test_success_resets_subject_not_source_and_expired_window_restarts(self):
        self.attempt()
        self.attempt()
        ok = self.attempt(callback=lambda _: "secret-session-token")
        self.assertTrue(ok.allowed)
        self.assertEqual(ok.value, "secret-session-token")
        self.assertNotIn("secret-session-token", repr(ok))
        buckets = self.connection.scalars(select(AuthAttemptBucket.failures)).all()
        self.assertEqual(sorted(buckets), [0, 2])
        self.connection.execute(
            update(AuthAttemptBucket.__table__).values(
                window_started_at=func.clock_timestamp() - text("interval '16 minutes'")
            )
        )
        failure = self.attempt()
        self.assertFalse(failure.throttled)
        self.assertEqual(
            sorted(self.connection.scalars(select(AuthAttemptBucket.failures)).all()), [1, 1]
        )
        self.assertEqual(
            self.connection.scalar(select(func.count()).select_from(AuthFailureEvent)), 3
        )

    def test_thirty_source_failures_block_new_identifiers_and_invalid_context_fails_closed(self):
        for n in range(30):
            self.attempt(identifier=f"new-person-{n}")
        calls = []
        blocked = self.attempt(identifier="brand-new", callback=lambda _: calls.append(True))
        self.assertTrue(blocked.throttled)
        self.assertFalse(calls)
        self.assertEqual(
            self.connection.scalar(select(func.count()).select_from(AuthFailureEvent)), 31
        )
        with self.assertRaises(ValueError):
            self.attempt(ip="spoofed, forwarded")
        with self.assertRaises(ValueError):
            guarded_authentication(
                self.connection,
                surface="OWNER_LOGIN",
                identifier="owner",
                source_ip="::1",
                pepper=b"too short",
                authenticate=lambda _: True,
                denied_by=(ValueError,),
            )
        self.assertEqual(
            self.connection.scalar(select(func.count()).select_from(AuthFailureEvent)), 31
        )


if __name__ == "__main__":
    unittest.main()
