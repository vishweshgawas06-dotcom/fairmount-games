"""PostgreSQL-only internal session validation tests; no HTTP login exists."""

import hashlib
import os
import secrets
import unittest
from datetime import timedelta

from fairmount_api.db.models import Account, AccountSession
from fairmount_api.identity.session_validation import resolve_session
from sqlalchemy import create_engine, func, insert, select, text, update

from infrastructure.local_db_url import local_database_url


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class SessionValidationTests(unittest.TestCase):
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

    def seeded(self, role="PLAYER", **changes):
        account_id = self.connection.execute(
            insert(Account.__table__).values(role=role).returning(Account.id)
        ).scalar_one()
        raw = secrets.token_urlsafe(32)
        idle = "15 minutes" if role == "OWNER" else "30 minutes"
        absolute = {"OWNER": "8 hours", "AGENT": "12 hours", "PLAYER": "24 hours"}[role]
        values = {
            "account_id": account_id,
            "role_at_issue": role,
            "token_digest": hashlib.sha256(raw.encode("ascii")).hexdigest(),
            "issued_at": func.now(),
            "last_seen_at": func.now(),
            "idle_expires_at": func.now() + text(f"interval '{idle}'"),
            "absolute_expires_at": func.now() + text(f"interval '{absolute}'"),
            "mfa_verified_at": func.now() if role == "OWNER" else None,
            **changes,
        }
        session_id = self.connection.execute(
            insert(AccountSession.__table__).values(**values).returning(AccountSession.id)
        ).scalar_one()
        return account_id, session_id, raw

    def test_valid_token_slides_idle_but_not_absolute(self) -> None:
        for role in ("OWNER", "AGENT", "PLAYER"):
            with self.subTest(role=role):
                account_id, session_id, raw = self.seeded(role)
                result = resolve_session(self.connection, raw)
                self.assertEqual(
                    (result.account_id, result.session_id, result.role),
                    (account_id, session_id, role),
                )
                self.assertEqual(result.mfa_verified_at is not None, role == "OWNER")
                row = self.connection.execute(
                    select(
                        AccountSession.issued_at,
                        AccountSession.last_seen_at,
                        AccountSession.idle_expires_at,
                        AccountSession.absolute_expires_at,
                    ).where(AccountSession.id == session_id)
                ).one()
                self.assertGreaterEqual(row.last_seen_at, row.issued_at)
                self.assertLessEqual(row.idle_expires_at, row.absolute_expires_at)
                self.assertEqual(
                    row.idle_expires_at,
                    min(
                        row.last_seen_at + timedelta(minutes=15 if role == "OWNER" else 30),
                        row.absolute_expires_at,
                    ),
                )

    def test_bad_token_and_missing_token_do_not_touch_session(self) -> None:
        _, session_id, raw = self.seeded()
        before = self.connection.scalar(
            select(AccountSession.last_seen_at).where(AccountSession.id == session_id)
        )
        for token in ("", "short", "-" * 43, raw + "!", None, 12):
            self.assertIsNone(resolve_session(self.connection, token))
        self.assertEqual(
            self.connection.scalar(
                select(AccountSession.last_seen_at).where(AccountSession.id == session_id)
            ),
            before,
        )

    def test_revoked_disabled_idle_and_absolute_expired_are_rejected(self) -> None:
        account, session_id, raw = self.seeded()
        self.connection.execute(
            update(AccountSession.__table__)
            .where(AccountSession.id == session_id)
            .values(revoked_at=func.now())
        )
        self.assertIsNone(resolve_session(self.connection, raw))
        self.assertIsNotNone(
            self.connection.scalar(
                select(AccountSession.revoked_at).where(AccountSession.id == session_id)
            )
        )

        account, session_id, raw = self.seeded()
        self.connection.execute(
            update(Account.__table__).where(Account.id == account).values(status="DISABLED")
        )
        self.assertIsNone(resolve_session(self.connection, raw))
        self.assertIsNotNone(
            self.connection.scalar(
                select(AccountSession.revoked_at).where(AccountSession.id == session_id)
            )
        )

        _, session_id, raw = self.seeded(
            issued_at=func.now() - text("interval '45 minutes'"),
            last_seen_at=func.now() - text("interval '31 minutes'"),
            idle_expires_at=func.now() - text("interval '1 minute'"),
            absolute_expires_at=func.now()
            - text("interval '45 minutes'")
            + text("interval '24 hours'"),
        )
        self.assertIsNone(resolve_session(self.connection, raw))
        self.assertIsNotNone(
            self.connection.scalar(
                select(AccountSession.revoked_at).where(AccountSession.id == session_id)
            )
        )

        _, session_id, raw = self.seeded(
            issued_at=func.now() - text("interval '25 hours'"),
            last_seen_at=func.now() - text("interval '24 hours'"),
            idle_expires_at=func.now()
            - text("interval '24 hours'")
            + text("interval '30 minutes'"),
            absolute_expires_at=func.now() - text("interval '1 hour'"),
        )
        self.assertIsNone(resolve_session(self.connection, raw))
        self.assertIsNotNone(
            self.connection.scalar(
                select(AccountSession.revoked_at).where(AccountSession.id == session_id)
            )
        )


if __name__ == "__main__":
    unittest.main()
