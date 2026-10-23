"""Real PostgreSQL contention with a separate, disposable migrated schema."""

import importlib.util
import os
import secrets
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fairmount_api.db.models import Account, AccountSession, AccountWallet, PointOperation
from fairmount_api.identity.session_validation import session_token_digest
from fairmount_api.point_accounting import (
    PointActionUnavailable,
    issue_owner_points,
    transfer_owner_points,
)
from fairmount_api.point_reconciliation import reconcile_points
from sqlalchemy import create_engine, func, insert, select, text

from infrastructure.local_db_url import local_database_url

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class PointContentionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = "fm_race_" + secrets.token_hex(
            8
        )  # SQL identifier generated here, not user input.
        cls.admin_engine = create_engine(local_database_url(test=True))
        with cls.admin_engine.begin() as connection:
            connection.execute(text(f"CREATE SCHEMA {cls.schema}"))
        cls.engine = create_engine(
            local_database_url(test=True),
            connect_args={"options": f"-csearch_path={cls.schema},public"},
            pool_size=4,
        )
        try:
            with cls.engine.begin() as connection:
                context = MigrationContext.configure(connection)
                with Operations.context(context):
                    for path in sorted(VERSIONS.glob("*.py")):
                        spec = importlib.util.spec_from_file_location(path.stem, path)
                        if spec is None or spec.loader is None:
                            raise RuntimeError(f"Migration cannot load: {path.name}")
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        module.upgrade()
            with cls.engine.begin() as connection:
                cls.owner = connection.execute(
                    insert(Account.__table__).values(role="OWNER").returning(Account.id)
                ).scalar_one()
                cls.players = [
                    connection.execute(
                        insert(Account.__table__).values(role="PLAYER").returning(Account.id)
                    ).scalar_one()
                    for _ in range(3)
                ]
                cls.token = secrets.token_urlsafe(32)
                connection.execute(
                    insert(AccountSession.__table__).values(
                        account_id=cls.owner,
                        role_at_issue="OWNER",
                        token_digest=session_token_digest(cls.token),
                        issued_at=func.now() - text("interval '5 minutes'"),
                        last_seen_at=func.now(),
                        idle_expires_at=func.now() + text("interval '15 minutes'"),
                        absolute_expires_at=func.now() + text("interval '7 hours 55 minutes'"),
                        mfa_verified_at=func.now() - text("interval '5 minutes'"),
                    )
                )
                issue_owner_points(
                    connection,
                    cls.token,
                    amount=100,
                    reason="contention fixture",
                    idempotency_key="seed",
                )
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "engine"):
            cls.engine.dispose()
        with cls.admin_engine.begin() as connection:
            connection.execute(text(f"DROP SCHEMA {cls.schema} CASCADE"))
        cls.admin_engine.dispose()

    def test_double_spend_and_simultaneous_idempotent_retry(self) -> None:
        barrier = Barrier(2)

        def competing(player, key):
            barrier.wait(timeout=10)
            try:
                with self.engine.begin() as connection:
                    return transfer_owner_points(
                        connection,
                        self.token,
                        member_account_id=player,
                        amount=70,
                        to_member=True,
                        reason="contention",
                        idempotency_key=key,
                    )
            except PointActionUnavailable:
                return None

        inputs = zip(self.players[:2], ("a", "b"), strict=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda args: competing(*args), inputs))
        self.assertEqual(sum(result is not None for result in results), 1)
        with self.engine.begin() as connection:
            balances = [
                connection.scalar(
                    select(AccountWallet.balance).where(AccountWallet.account_id == account)
                )
                for account in (self.owner, *self.players)
            ]
        self.assertEqual(balances[0], 30)
        self.assertEqual(sorted(balances[1:]), [0, 0, 70])

        retry_barrier = Barrier(2)

        def retry():
            retry_barrier.wait(timeout=10)
            with self.engine.begin() as connection:
                return transfer_owner_points(
                    connection,
                    self.token,
                    member_account_id=self.players[2],
                    amount=5,
                    to_member=True,
                    reason="same intent",
                    idempotency_key="same-key",
                )

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(lambda _: retry(), range(2)))
        self.assertEqual(first.operation_id, second.operation_id)
        self.assertEqual({first.replayed, second.replayed}, {False, True})
        with self.engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection:
            with connection.begin():
                report = reconcile_points(connection)
                count = connection.scalar(select(func.count()).select_from(PointOperation))
                owner_balance = connection.scalar(
                    select(AccountWallet.balance).where(AccountWallet.account_id == self.owner)
                )
        self.assertTrue(report.balanced)
        self.assertEqual((report.current_supply, report.explicitly_issued), (100, 100))
        self.assertEqual(count, 3)  # issuance, one funded player, one same-key transfer
        self.assertEqual(owner_balance, 25)


if __name__ == "__main__":
    unittest.main()
