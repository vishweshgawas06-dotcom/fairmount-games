"""Real PostgreSQL contention with a separate, disposable migrated schema."""

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
    AuthAttemptBucket,
    AuthFailureEvent,
    GameReserve,
    PointOperation,
    RouletteBet,
    RouletteRound,
)
from fairmount_api.identity.auth_attempts import guarded_authentication
from fairmount_api.identity.session_validation import session_token_digest
from fairmount_api.point_accounting import (
    PointActionUnavailable,
    issue_owner_points,
    transfer_owner_points,
)
from fairmount_api.point_reconciliation import reconcile_points
from fairmount_api.reserve_funding import fund_game_reserve, withdraw_surplus_reserve
from fairmount_api.roulette.admission import BetUnavailable, place_bet
from fairmount_api.roulette.round_clock import close_round, open_round
from fairmount_api.roulette.settlement import (
    SettlementUnavailable,
    refund_void_round,
    settle_round,
)
from sqlalchemy import create_engine, func, insert, select, text, update

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

    def test_auth_failure_window_serializes_six_committed_connections(self) -> None:
        barrier = Barrier(6)

        def wrong_password(_):
            barrier.wait(timeout=10)

            def reject(_connection):
                raise ValueError("generic credential denial")

            with self.engine.begin() as connection:
                return guarded_authentication(
                    connection,
                    surface="MEMBER_LOGIN",
                    identifier="PLAYER:missing-user",
                    source_ip="203.0.113.85",
                    pepper=b"separate-test-pepper-never-deploy-this-123",
                    authenticate=reject,
                    denied_by=(ValueError,),
                )

        with ThreadPoolExecutor(max_workers=6) as pool:
            outcomes = list(pool.map(wrong_password, range(6)))
        self.assertEqual(sum(not item.throttled for item in outcomes), 5)
        self.assertEqual(sum(item.throttled for item in outcomes), 1)
        self.assertTrue(all(not item.allowed for item in outcomes))
        with self.engine.begin() as connection:
            events = (
                connection.execute(
                    select(AuthFailureEvent.outcome).order_by(AuthFailureEvent.occurred_at)
                )
                .scalars()
                .all()
            )
            counts = sorted(connection.scalars(select(AuthAttemptBucket.failures)).all())
        self.assertEqual(sorted(events), ["FAILED"] * 5 + ["THROTTLED"])
        self.assertEqual(counts, [5, 5])

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

        # P11-T01b: owner funds reserve once, two independent players submit
        # identical winning positions. Both can afford a full stake, but the
        # reserve after a single stake covers 350 while two would owe 700.
        tokens = []
        with self.engine.begin() as connection:
            issue_owner_points(
                connection,
                self.token,
                amount=1000,
                reason="additional supply",
                idempotency_key="bet-seed",
            )
            fund_game_reserve(
                connection,
                self.token,
                amount=340,
                reason="fund one outcome",
                idempotency_key="bet-reserve",
            )
            for n, player in enumerate(self.players[:2]):
                transfer_owner_points(
                    connection,
                    self.token,
                    member_account_id=player,
                    amount=100,
                    to_member=True,
                    reason="player stake",
                    idempotency_key=f"bet-player-{n}",
                )
                token = secrets.token_urlsafe(32)
                connection.execute(
                    insert(AccountSession.__table__).values(
                        account_id=player,
                        role_at_issue="PLAYER",
                        token_digest=session_token_digest(token),
                        issued_at=func.now(),
                        last_seen_at=func.now(),
                        idle_expires_at=func.now() + text("interval '30 minutes'"),
                        absolute_expires_at=func.now() + text("interval '24 hours'"),
                    )
                )
                tokens.append(token)
            baseline_player_balances = [
                connection.scalar(
                    select(AccountWallet.balance).where(AccountWallet.account_id == player)
                )
                for player in self.players[:2]
            ]
            round_id = open_round(connection)

        bet_barrier = Barrier(2)

        def competing_bet(n):
            bet_barrier.wait(timeout=10)
            try:
                with self.engine.begin() as connection:
                    return place_bet(
                        connection,
                        tokens[n],
                        round_id=round_id,
                        selection_key="straight:17",
                        requested=10,
                        idempotency_key=f"bet-race-{n}",
                    )
            except BetUnavailable:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            admitted = list(pool.map(competing_bet, range(2)))
        self.assertEqual(sum(bet is not None for bet in admitted), 1)
        with self.engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection:
            with connection.begin():
                report = reconcile_points(connection)
                reserve_balance = connection.scalar(select(GameReserve.balance))
                bet_count = connection.scalar(select(func.count()).select_from(RouletteBet))
                player_balances = [
                    connection.scalar(
                        select(AccountWallet.balance).where(AccountWallet.account_id == player)
                    )
                    for player in self.players[:2]
                ]
        self.assertTrue(report.balanced)
        self.assertEqual((report.current_supply, report.explicitly_issued), (1100, 1100))
        self.assertEqual((reserve_balance, bet_count), (350, 1))
        self.assertEqual(sum(baseline_player_balances) - sum(player_balances), 10)
        self.assertEqual(
            sum(
                before != after
                for before, after in zip(baseline_player_balances, player_balances, strict=True)
            ),
            1,
        )

        # Independently delivered void attempts must serialize through the
        # reserve and terminal round row: only the accepted bet is refunded.
        void_barrier = Barrier(2)

        def competing_void():
            void_barrier.wait(timeout=10)
            with self.engine.begin() as connection:
                return refund_void_round(
                    connection,
                    round_id,
                    incident_reason="test-only concurrent void delivery",
                )

        with ThreadPoolExecutor(max_workers=2) as pool:
            voids = list(pool.map(lambda _: competing_void(), range(2)))
        self.assertEqual({result.replayed for result in voids}, {False, True})
        self.assertEqual([result.total_credited for result in voids], [10, 10])
        with self.engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection:
            with connection.begin():
                report = reconcile_points(connection)
                reserve_balance = connection.scalar(select(GameReserve.balance))
                refund_count = connection.scalar(
                    select(func.count())
                    .select_from(PointOperation)
                    .where(PointOperation.kind == "VOID_REFUND")
                )
                restored = [
                    connection.scalar(
                        select(AccountWallet.balance).where(AccountWallet.account_id == player)
                    )
                    for player in self.players[:2]
                ]
        self.assertTrue(report.balanced)
        self.assertEqual((reserve_balance, refund_count), (340, 1))
        self.assertEqual(restored, baseline_player_balances)

        # P11-T01f: admission racing a trusted void must be wholly accepted
        # and refunded, or rejected before acceptance. Either order leaves
        # the wallet/reserve at the pre-race values, with no live liability.
        with self.engine.begin() as connection:
            next_round = open_round(connection)
        terminal_barrier = Barrier(2)

        def last_bet():
            terminal_barrier.wait(timeout=10)
            try:
                with self.engine.begin() as connection:
                    return place_bet(
                        connection,
                        tokens[0],
                        round_id=next_round,
                        selection_key="straight:17",
                        requested=10,
                        idempotency_key="bet-against-void",
                    )
            except BetUnavailable:
                return None

        def last_void():
            terminal_barrier.wait(timeout=10)
            with self.engine.begin() as connection:
                return refund_void_round(
                    connection,
                    next_round,
                    incident_reason="test-only admission/void contention",
                )

        with ThreadPoolExecutor(max_workers=2) as pool:
            bet_future = pool.submit(last_bet)
            void_future = pool.submit(last_void)
            raced_bet = bet_future.result()
            raced_void = void_future.result()
        expected_bets = int(raced_bet is not None)
        self.assertEqual(raced_void.total_credited, 10 * expected_bets)
        with self.engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection:
            with connection.begin():
                report = reconcile_points(connection)
                reserve_balance = connection.scalar(select(GameReserve.balance))
                final_bets = connection.scalar(
                    select(func.count())
                    .select_from(RouletteBet)
                    .where(RouletteBet.round_id == next_round)
                )
                new_refunds = connection.scalar(
                    select(func.count())
                    .select_from(PointOperation)
                    .where(
                        PointOperation.kind == "VOID_REFUND",
                        PointOperation.context_id == next_round,
                    )
                )
                restored = [
                    connection.scalar(
                        select(AccountWallet.balance).where(AccountWallet.account_id == player)
                    )
                    for player in self.players[:2]
                ]
        self.assertTrue(report.balanced)
        self.assertEqual(
            (reserve_balance, final_bets, new_refunds), (340, expected_bets, expected_bets)
        )
        self.assertEqual(restored, baseline_player_balances)

        # D-06a: once a result exists, settlement wins even if a trusted
        # incident-void attempt arrives first. No worker may refund this bet
        # rather than pay its persisted, independently selected winner.
        with self.engine.begin() as connection:
            final_round = open_round(connection)
        with self.engine.begin() as connection:
            place_bet(
                connection,
                tokens[0],
                round_id=final_round,
                selection_key="straight:17",
                requested=10,
                idempotency_key="bet-before-terminal-race",
            )
        with self.engine.begin() as connection:
            opened = connection.scalar(select(func.clock_timestamp())) - timedelta(seconds=61)
            # Privileged isolated-schema test fixture only; restore the trigger
            # before running the actual transition and concurrent services.
            connection.execute(text("ALTER TABLE roulette_rounds DISABLE TRIGGER tr_round_guard"))
            connection.execute(
                update(RouletteRound.__table__)
                .where(RouletteRound.id == final_round)
                .values(
                    opens_at=opened,
                    closes_at=opened + timedelta(seconds=50),
                    reveal_at=opened + timedelta(seconds=60),
                )
            )
            connection.execute(text("ALTER TABLE roulette_rounds ENABLE TRIGGER tr_round_guard"))
            self.assertEqual(close_round(connection, final_round, _test_rng=lambda: 17), 17)

        final_barrier = Barrier(2)

        def competing_terminal(void):
            final_barrier.wait(timeout=10)
            try:
                with self.engine.begin() as connection:
                    if void:
                        return refund_void_round(
                            connection,
                            final_round,
                            incident_reason="test-only terminal race",
                        )
                    return settle_round(connection, final_round)
            except SettlementUnavailable:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            settled_future = pool.submit(competing_terminal, False)
            refunded_future = pool.submit(competing_terminal, True)
            settled = settled_future.result()
            refunded = refunded_future.result()
        self.assertIsNotNone(settled)
        self.assertIsNone(refunded)
        self.assertEqual(settled.total_credited, 350)
        with self.engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection:
            with connection.begin():
                report = reconcile_points(connection)
                state = connection.scalar(
                    select(RouletteRound.state).where(RouletteRound.id == final_round)
                )
                balance = connection.scalar(select(GameReserve.balance))
                player_balance = connection.scalar(
                    select(AccountWallet.balance).where(AccountWallet.account_id == self.players[0])
                )
                operations = connection.execute(
                    select(PointOperation.kind, PointOperation.amount).where(
                        PointOperation.context_id == final_round,
                        PointOperation.kind.in_(("PAYOUT", "VOID_REFUND")),
                    )
                ).all()
        self.assertTrue(report.balanced)
        self.assertEqual(state, "SETTLED")
        self.assertEqual(balance, 0)
        self.assertEqual(player_balance, baseline_player_balances[0] + 340)
        self.assertEqual(operations, [("PAYOUT", 350)])

        # P05-T02f: one additional 350-point liability cannot coexist with
        # a ten-point withdrawal from a 340-point reserve. The reserve lock
        # permits only one request to succeed, without consuming the other's
        # stake or handing an accepted winner an unfunded promise.
        with self.engine.begin() as connection:
            fund_game_reserve(
                connection,
                self.token,
                amount=340,
                reason="fund withdrawal contention",
                idempotency_key="race-refund",
            )
            withdraw_round = open_round(connection)
            owner_before = connection.scalar(
                select(AccountWallet.balance).where(AccountWallet.account_id == self.owner)
            )
        withdrawal_barrier = Barrier(2)

        def competing_withdrawal():
            withdrawal_barrier.wait(timeout=10)
            try:
                with self.engine.begin() as connection:
                    return withdraw_surplus_reserve(
                        connection,
                        self.token,
                        amount=10,
                        reason="only unfunded surplus",
                        idempotency_key="withdraw-race",
                    )
            except PointActionUnavailable:
                return None

        def competing_admission():
            withdrawal_barrier.wait(timeout=10)
            try:
                with self.engine.begin() as connection:
                    return place_bet(
                        connection,
                        tokens[0],
                        round_id=withdraw_round,
                        selection_key="straight:17",
                        requested=10,
                        idempotency_key="bet-withdraw-race",
                    )
            except BetUnavailable:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            bet_future = pool.submit(competing_admission)
            withdrawal_future = pool.submit(competing_withdrawal)
            competing_bet_result = bet_future.result()
            withdrawn = withdrawal_future.result()
        self.assertEqual(sum(result is not None for result in (competing_bet_result, withdrawn)), 1)
        bet_won = competing_bet_result is not None
        with self.engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection:
            with connection.begin():
                report = reconcile_points(connection)
                reserve_balance = connection.scalar(select(GameReserve.balance))
                owner_after = connection.scalar(
                    select(AccountWallet.balance).where(AccountWallet.account_id == self.owner)
                )
                player_after = connection.scalar(
                    select(AccountWallet.balance).where(AccountWallet.account_id == self.players[0])
                )
                accepted = connection.scalar(
                    select(func.count())
                    .select_from(RouletteBet)
                    .where(RouletteBet.round_id == withdraw_round)
                )
        self.assertTrue(report.balanced)
        self.assertEqual((reserve_balance, accepted), (350, 1) if bet_won else (330, 0))
        self.assertEqual(owner_after, owner_before + (0 if bet_won else 10))
        self.assertEqual(player_after, player_balance - (10 if bet_won else 0))


if __name__ == "__main__":
    unittest.main()
