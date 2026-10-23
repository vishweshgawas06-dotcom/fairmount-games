"""PostgreSQL round cutoff, one outcome, immutable bets and funded stake linkage."""

import os
import unittest
import uuid

from fairmount_api.db.models import (
    Account,
    PointLedgerEntry,
    PointOperation,
    RouletteBet,
    RouletteRound,
)
from fairmount_api.roulette.round_clock import RoundUnavailable, close_round, open_round
from sqlalchemy import create_engine, func, insert, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from infrastructure.local_db_url import local_database_url


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class RoundStorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_engine(local_database_url(test=True))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        self.owner = self.connection.execute(
            insert(Account.__table__).values(role="OWNER").returning(Account.id)
        ).scalar_one()
        self.player = self.connection.execute(
            insert(Account.__table__).values(role="PLAYER").returning(Account.id)
        ).scalar_one()

    def tearDown(self) -> None:
        self.transaction.rollback()
        self.connection.close()

    def operation(
        self,
        *,
        kind,
        actor,
        role,
        amount,
        source=None,
        target=None,
        source_reserve=False,
        target_reserve=False,
        context_id=None,
    ):
        return self.connection.execute(
            insert(PointOperation.__table__)
            .values(
                kind=kind,
                actor_account_id=actor,
                actor_role=role,
                amount=amount,
                source_wallet_id=source,
                target_wallet_id=target,
                source_reserve=source_reserve,
                target_reserve=target_reserve,
                context_id=context_id,
                reason="round storage test",
                idempotency_key=uuid.uuid4().hex,
                request_fingerprint="b" * 64,
            )
            .returning(PointOperation.id)
        ).scalar_one()

    def effect(self, op, delta, *, wallet=None, reserve=False):
        self.connection.execute(
            insert(PointLedgerEntry.__table__).values(
                operation_id=op,
                delta=delta,
                wallet_account_id=wallet,
                reserve_id=1 if reserve else None,
            )
        )

    def fund_player(self):
        issue = self.operation(
            kind="OWNER_ISSUE", actor=self.owner, role="OWNER", amount=100, target=self.owner
        )
        self.effect(issue, 100, wallet=self.owner)
        transfer = self.operation(
            kind="OWNER_TRANSFER",
            actor=self.owner,
            role="OWNER",
            amount=20,
            source=self.owner,
            target=self.player,
        )
        self.effect(transfer, -20, wallet=self.owner)
        self.effect(transfer, 20, wallet=self.player)

    def backdated_round(self):
        # Test fixture only; live round creation uses clock_timestamp() in open_round.
        return self.connection.execute(
            insert(RouletteRound.__table__)
            .values(
                state="OPEN",
                opens_at=func.now() - text("interval '60 seconds'"),
                closes_at=func.now() - text("interval '10 seconds'"),
                reveal_at=func.now(),
            )
            .returning(RouletteRound.id)
        ).scalar_one()

    def test_global_open_and_cutoff_cannot_be_client_driven(self):
        current = open_round(self.connection)
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            open_round(self.connection)
        with self.assertRaises(RoundUnavailable):
            close_round(self.connection, current, _test_rng=lambda: 17)
        self.assertIsNone(
            self.connection.scalar(
                select(RouletteRound.winning_number).where(RouletteRound.id == current)
            )
        )
        self.assertEqual(
            self.connection.scalar(
                select(RouletteRound.closes_at - RouletteRound.opens_at).where(
                    RouletteRound.id == current
                )
            ).total_seconds(),
            50,
        )

    def test_persisted_result_is_once_only_and_rng_not_recalled(self):
        round_id = self.backdated_round()
        calls = []

        def choose():
            calls.append(1)
            return 0

        self.assertEqual(close_round(self.connection, round_id, _test_rng=choose), 0)
        self.assertEqual(close_round(self.connection, round_id, _test_rng=lambda: 37), 0)
        self.assertEqual(calls, [1])
        with self.assertRaises(DBAPIError), self.connection.begin_nested():
            self.connection.execute(
                update(RouletteRound.__table__)
                .where(RouletteRound.id == round_id)
                .values(winning_number=17)
            )
        with self.assertRaises(DBAPIError), self.connection.begin_nested():
            self.connection.execute(
                update(RouletteRound.__table__)
                .where(RouletteRound.id == round_id)
                .values(state="OPEN")
            )
        self.assertEqual(close_round(self.connection, round_id), 0)

    def test_invalid_rng_and_invalid_round_do_not_persist_result(self):
        round_id = self.backdated_round()
        for bad in (True, -1, 37, 5.0):
            with self.subTest(bad=bad), self.assertRaises(RuntimeError):
                close_round(self.connection, round_id, _test_rng=lambda bad=bad: bad)
        with self.assertRaises(RoundUnavailable):
            close_round(self.connection, uuid.uuid4())
        self.assertIsNone(
            self.connection.scalar(
                select(RouletteRound.winning_number).where(RouletteRound.id == round_id)
            )
        )
        self.assertEqual(close_round(self.connection, round_id, _test_rng=lambda: 36), 36)

    def test_one_accepted_bet_has_exact_one_corresponding_reserved_stake(self):
        self.fund_player()
        round_id = open_round(self.connection)
        bet_id = uuid.uuid4()
        stake = self.operation(
            kind="BET_STAKE",
            actor=self.player,
            role="PLAYER",
            amount=10,
            source=self.player,
            target_reserve=True,
            context_id=bet_id,
        )
        self.effect(stake, -10, wallet=self.player)
        self.effect(stake, 10, reserve=True)
        self.connection.execute(
            insert(RouletteBet.__table__).values(
                id=bet_id,
                round_id=round_id,
                player_account_id=self.player,
                operation_id=stake,
                selection_key="straight:17",
                accepted_stake=10,
            )
        )
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertEqual(
            self.connection.scalar(
                select(RouletteBet.accepted_stake).where(RouletteBet.id == bet_id)
            ),
            10,
        )
        with self.assertRaises(DBAPIError), self.connection.begin_nested():
            self.connection.execute(
                update(RouletteBet.__table__)
                .where(RouletteBet.id == bet_id)
                .values(accepted_stake=15)
            )

    def test_orphan_or_mismatched_stakes_fail_without_changing_ledger(self):
        self.fund_player()
        round_id = open_round(self.connection)
        with self.assertRaises(DBAPIError), self.connection.begin_nested():
            bet_id = uuid.uuid4()
            stake = self.operation(
                kind="BET_STAKE",
                actor=self.player,
                role="PLAYER",
                amount=10,
                source=self.player,
                target_reserve=True,
                context_id=bet_id,
            )
            self.effect(stake, -10, wallet=self.player)
            self.effect(stake, 10, reserve=True)
            self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        with self.assertRaises(DBAPIError), self.connection.begin_nested():
            bet_id = uuid.uuid4()
            stake = self.operation(
                kind="BET_STAKE",
                actor=self.player,
                role="PLAYER",
                amount=10,
                source=self.player,
                target_reserve=True,
                context_id=bet_id,
            )
            self.effect(stake, -10, wallet=self.player)
            self.effect(stake, 10, reserve=True)
            self.connection.execute(
                insert(RouletteBet.__table__).values(
                    id=bet_id,
                    round_id=round_id,
                    player_account_id=self.player,
                    operation_id=stake,
                    selection_key="straight:17",
                    accepted_stake=15,
                )
            )
            self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertEqual(self.connection.scalar(select(func.count()).select_from(RouletteBet)), 0)
        self.assertEqual(
            self.connection.scalar(select(func.count()).select_from(PointOperation)), 2
        )

    def test_expired_round_rejects_stake_and_spoofed_client_time(self):
        self.fund_player()
        round_id = self.backdated_round()
        with self.assertRaises(DBAPIError), self.connection.begin_nested():
            bet_id = uuid.uuid4()
            stake = self.operation(
                kind="BET_STAKE",
                actor=self.player,
                role="PLAYER",
                amount=10,
                source=self.player,
                target_reserve=True,
                context_id=bet_id,
            )
            self.effect(stake, -10, wallet=self.player)
            self.effect(stake, 10, reserve=True)
            self.connection.execute(
                insert(RouletteBet.__table__).values(
                    id=bet_id,
                    round_id=round_id,
                    player_account_id=self.player,
                    operation_id=stake,
                    selection_key="straight:17",
                    accepted_stake=10,
                    accepted_at=func.now() - text("interval '60 seconds'"),
                )
            )
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertEqual(self.connection.scalar(select(func.count()).select_from(RouletteBet)), 0)
        self.assertEqual(
            self.connection.scalar(select(func.count()).select_from(PointOperation)), 2
        )


if __name__ == "__main__":
    unittest.main()
