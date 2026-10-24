"""Committed, independent PostgreSQL connections serialize private rebet bundles."""

import importlib.util
import os
import secrets
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fairmount_api.db.models import (
    Account,
    AccountSession,
    AccountWallet,
    GameReserve,
    RouletteBet,
    RouletteRound,
)
from fairmount_api.identity.session_validation import session_token_digest
from fairmount_api.point_accounting import issue_owner_points, transfer_owner_points
from fairmount_api.point_reconciliation import reconcile_points
from fairmount_api.reserve_funding import fund_game_reserve
from fairmount_api.roulette.admission import place_bet
from fairmount_api.roulette.rebet import RebetUnavailable, repeat_previous_bets
from fairmount_api.roulette.round_clock import close_round, open_round
from fairmount_api.roulette.settlement import settle_round
from sqlalchemy import create_engine, func, insert, select, text, update

from infrastructure.local_db_url import local_database_url

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class RebetContentionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = "fm_rebet_" + secrets.token_hex(8)
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
    def tearDownClass(cls):
        if hasattr(cls, "engine"):
            cls.engine.dispose()
        with cls.admin_engine.begin() as connection:
            connection.execute(text(f"DROP SCHEMA {cls.schema} CASCADE"))
        cls.admin_engine.dispose()

    @staticmethod
    def age_round(connection, round_id):
        opened = connection.scalar(select(func.clock_timestamp())) - timedelta(seconds=61)
        connection.execute(text("ALTER TABLE roulette_rounds DISABLE TRIGGER tr_round_guard"))
        connection.execute(
            update(RouletteRound.__table__)
            .where(RouletteRound.id == round_id)
            .values(
                opens_at=opened,
                closes_at=opened + timedelta(seconds=50),
                reveal_at=opened + timedelta(seconds=60),
            )
        )
        connection.execute(text("ALTER TABLE roulette_rounds ENABLE TRIGGER tr_round_guard"))

    def test_two_committed_retries_and_distinct_requests(self):
        with self.engine.begin() as connection:
            owner = connection.execute(
                insert(Account.__table__).values(role="OWNER").returning(Account.id)
            ).scalar_one()
            player = connection.execute(
                insert(Account.__table__).values(role="PLAYER").returning(Account.id)
            ).scalar_one()
            owner_token = secrets.token_urlsafe(32)
            player_token = secrets.token_urlsafe(32)
            for account, role, token in (
                (owner, "OWNER", owner_token),
                (player, "PLAYER", player_token),
            ):
                connection.execute(
                    insert(AccountSession.__table__).values(
                        account_id=account,
                        role_at_issue=role,
                        token_digest=session_token_digest(token),
                        issued_at=func.now() - text("interval '5 minutes'")
                        if role == "OWNER"
                        else func.now(),
                        last_seen_at=func.now(),
                        idle_expires_at=func.now() + text("interval '15 minutes'"),
                        absolute_expires_at=func.now() + text("interval '7 hours'"),
                        mfa_verified_at=func.now() - text("interval '5 minutes'")
                        if role == "OWNER"
                        else None,
                    )
                )
            issue_owner_points(
                connection,
                owner_token,
                amount=1000,
                reason="race seed",
                idempotency_key="seed-issue",
            )
            transfer_owner_points(
                connection,
                owner_token,
                member_account_id=player,
                amount=100,
                to_member=True,
                reason="race seed",
                idempotency_key="seed-player",
            )
            fund_game_reserve(
                connection,
                owner_token,
                amount=340,
                reason="race seed",
                idempotency_key="seed-reserve",
            )
            source = open_round(connection)
            place_bet(
                connection,
                player_token,
                round_id=source,
                selection_key="straight:17",
                requested=10,
                idempotency_key="original",
            )
            self.age_round(connection, source)
            close_round(connection, source, _test_rng=lambda: 0)
            settle_round(connection, source)
            target = open_round(connection)

        def race(keys, target_id):
            barrier = Barrier(2)

            def attempt(key):
                barrier.wait(timeout=10)
                try:
                    with self.engine.begin() as connection:
                        return repeat_previous_bets(
                            connection,
                            player_token,
                            target_round_id=target_id,
                            idempotency_key=key,
                        )
                except RebetUnavailable:
                    return None

            with ThreadPoolExecutor(max_workers=2) as pool:
                return list(pool.map(attempt, keys))

        same = race(("same", "same"), target)
        self.assertEqual(sorted(result.replayed for result in same), [False, True])
        self.assertEqual(same[0].bets[0].bet_id, same[1].bets[0].bet_id)
        with self.engine.begin() as connection:
            self.assertEqual(connection.scalar(select(func.count()).select_from(RouletteBet)), 2)
            self.assertEqual(
                connection.scalar(
                    select(AccountWallet.balance).where(AccountWallet.account_id == player)
                ),
                80,
            )
            self.assertEqual(
                connection.scalar(select(GameReserve.balance).where(GameReserve.id == 1)), 360
            )
            self.age_round(connection, target)
            close_round(connection, target, _test_rng=lambda: 0)
            settle_round(connection, target)
            next_round = open_round(connection)

        distinct = race(("different-a", "different-b"), next_round)
        self.assertEqual(sum(result is not None for result in distinct), 1)
        with self.engine.begin() as connection:
            self.assertEqual(connection.scalar(select(func.count()).select_from(RouletteBet)), 3)
            self.assertEqual(
                connection.scalar(
                    select(AccountWallet.balance).where(AccountWallet.account_id == player)
                ),
                70,
            )
            self.assertEqual(
                connection.scalar(select(GameReserve.balance).where(GameReserve.id == 1)), 370
            )
            self.assertTrue(reconcile_points(connection).balanced)


if __name__ == "__main__":
    unittest.main()
