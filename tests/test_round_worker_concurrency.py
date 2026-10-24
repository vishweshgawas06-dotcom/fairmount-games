"""Two independently committed worker processes cannot open duplicate rounds."""

import importlib.util
import os
import secrets
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fairmount_api.db.models import RouletteRound
from fairmount_api.roulette.recovery import open_next_due_round
from sqlalchemy import create_engine, func, select, text

from infrastructure.local_db_url import local_database_url

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class RoundWorkerConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = "fm_worker_" + secrets.token_hex(8)
        cls.admin_engine = create_engine(local_database_url(test=True))
        with cls.admin_engine.begin() as connection:
            connection.execute(text(f"CREATE SCHEMA {cls.schema}"))
        cls.engine = create_engine(
            local_database_url(test=True),
            connect_args={"options": f"-csearch_path={cls.schema},public"},
            pool_size=3,
        )
        try:
            with cls.engine.begin() as connection:
                context = MigrationContext.configure(connection)
                with Operations.context(context):
                    for path in sorted(VERSIONS.glob("*.py")):
                        spec = importlib.util.spec_from_file_location(path.stem, path)
                        if spec is None or spec.loader is None:
                            raise RuntimeError(f"Cannot load migration {path.name}")
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        module.upgrade()
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

    def test_two_pollers_open_only_one_global_round(self) -> None:
        barrier = Barrier(2)

        def open_in_committed_connection(_):
            barrier.wait(timeout=10)
            with self.engine.begin() as connection:
                return open_next_due_round(connection)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(open_in_committed_connection, range(2)))
        self.assertEqual(sum(item is not None for item in results), 1)
        with self.engine.begin() as connection:
            stored = connection.execute(
                select(
                    RouletteRound.id,
                    RouletteRound.opens_at,
                    RouletteRound.closes_at,
                    RouletteRound.reveal_at,
                    RouletteRound.state,
                )
            ).one()
            self.assertEqual(stored.id, next(item for item in results if item is not None))
            self.assertEqual(stored.state, "OPEN")
            self.assertEqual(connection.scalar(select(func.count()).select_from(RouletteRound)), 1)
            self.assertEqual(
                stored.closes_at - stored.opens_at,
                connection.scalar(select(text("interval '50 seconds'"))),
            )
            self.assertEqual(
                stored.reveal_at - stored.opens_at,
                connection.scalar(select(text("interval '60 seconds'"))),
            )
            self.assertIsNone(open_next_due_round(connection))


if __name__ == "__main__":
    unittest.main()
