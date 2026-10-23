"""PostgreSQL constraints and triggers for the UUID point journal; no service/route."""

import os
import unittest
import uuid

from fairmount_api.db.models import (
    Account,
    AccountWallet,
    GameReserve,
    PointLedgerEntry,
    PointOperation,
)
from sqlalchemy import create_engine, insert, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from infrastructure.local_db_url import local_database_url


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class PointLedgerSchemaTests(unittest.TestCase):
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

    def account(self, role: str) -> uuid.UUID:
        return self.connection.execute(
            insert(Account.__table__).values(role=role).returning(Account.id)
        ).scalar_one()

    def balance(self, account: uuid.UUID) -> int:
        return self.connection.scalar(
            select(AccountWallet.balance).where(AccountWallet.account_id == account)
        )

    def reserve(self) -> int:
        return self.connection.scalar(select(GameReserve.balance).where(GameReserve.id == 1))

    def operation(self, kind: str, actor: uuid.UUID, role: str, amount: int, **kwargs) -> uuid.UUID:
        return self.connection.execute(
            insert(PointOperation.__table__)
            .values(
                kind=kind,
                actor_account_id=actor,
                actor_role=role,
                amount=amount,
                idempotency_key=uuid.uuid4().hex,
                request_fingerprint="a" * 64,
                reason="schema test",
                **kwargs,
            )
            .returning(PointOperation.id)
        ).scalar_one()

    def effect(self, operation_id: uuid.UUID, delta: int, *, wallet=None, reserve=False):
        return self.connection.execute(
            insert(PointLedgerEntry.__table__)
            .values(
                operation_id=operation_id,
                delta=delta,
                wallet_account_id=wallet,
                reserve_id=1 if reserve else None,
            )
            .returning(PointLedgerEntry.id)
        ).scalar_one()

    def issue(self, owner: uuid.UUID, amount: int) -> uuid.UUID:
        op = self.operation("OWNER_ISSUE", owner, "OWNER", amount, target_wallet_id=owner)
        self.effect(op, amount, wallet=owner)
        return op

    def test_wallets_start_at_zero_and_journal_drives_conserved_balances(self) -> None:
        owner, player = self.account("OWNER"), self.account("PLAYER")
        self.assertEqual((self.balance(owner), self.balance(player), self.reserve()), (0, 0, 0))
        self.issue(owner, 1000)
        transfer = self.operation(
            "OWNER_TRANSFER",
            owner,
            "OWNER",
            200,
            source_wallet_id=owner,
            target_wallet_id=player,
        )
        self.effect(transfer, -200, wallet=owner)
        self.effect(transfer, 200, wallet=player)
        fund = self.operation(
            "RESERVE_FUND",
            owner,
            "OWNER",
            300,
            source_wallet_id=owner,
            target_reserve=True,
        )
        self.effect(fund, -300, wallet=owner)
        self.effect(fund, 300, reserve=True)
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertEqual(
            (self.balance(owner), self.balance(player), self.reserve()), (500, 200, 300)
        )
        self.assertEqual(self.balance(owner) + self.balance(player) + self.reserve(), 1000)

    def test_operation_requires_exact_balanced_effects_on_commit(self) -> None:
        owner, player = self.account("OWNER"), self.account("PLAYER")
        with self.assertRaises(DBAPIError), self.connection.begin_nested():
            self.operation("OWNER_ISSUE", owner, "OWNER", 100, target_wallet_id=owner)
            self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        with self.assertRaises(DBAPIError), self.connection.begin_nested():
            op = self.operation(
                "OWNER_TRANSFER",
                owner,
                "OWNER",
                100,
                source_wallet_id=owner,
                target_wallet_id=player,
            )
            self.effect(op, 100, wallet=player)
            self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        with self.assertRaises(DBAPIError), self.connection.begin_nested():
            op = self.operation("OWNER_ISSUE", owner, "OWNER", 100, target_wallet_id=owner)
            self.effect(op, 100, wallet=player)
            self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        self.assertEqual((self.balance(owner), self.balance(player)), (0, 0))

    def test_negative_and_partial_transfer_rolls_back_entire_savepoint(self) -> None:
        owner, player = self.account("OWNER"), self.account("PLAYER")
        self.issue(owner, 10)
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            op = self.operation(
                "OWNER_TRANSFER",
                owner,
                "OWNER",
                11,
                source_wallet_id=owner,
                target_wallet_id=player,
            )
            self.effect(op, -11, wallet=owner)
            self.effect(op, 11, wallet=player)
        self.assertEqual((self.balance(owner), self.balance(player)), (10, 0))
        self.connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

    def test_direct_balance_and_history_mutation_are_blocked(self) -> None:
        owner = self.account("OWNER")
        op = self.issue(owner, 10)
        entry_id = self.connection.scalar(
            select(PointLedgerEntry.id).where(PointLedgerEntry.operation_id == op)
        )
        for statement in (
            update(AccountWallet.__table__)
            .where(AccountWallet.account_id == owner)
            .values(balance=15),
            update(GameReserve.__table__).where(GameReserve.id == 1).values(balance=10),
            update(PointLedgerEntry.__table__)
            .where(PointLedgerEntry.id == entry_id)
            .values(delta=100),
            update(PointOperation.__table__).where(PointOperation.id == op).values(amount=100),
            text("DELETE FROM game_reserve WHERE id = 1"),
            text("TRUNCATE point_ledger_entries"),
        ):
            with self.subTest(statement=str(statement)):
                with self.assertRaises(DBAPIError), self.connection.begin_nested():
                    self.connection.execute(statement)
        self.assertEqual((self.balance(owner), self.reserve()), (10, 0))

    def test_bad_roles_targets_shapes_and_idempotency_are_rejected(self) -> None:
        owner, agent, player = self.account("OWNER"), self.account("AGENT"), self.account("PLAYER")
        cases = (
            ("OWNER_ISSUE", agent, "AGENT", {"target_wallet_id": agent}),
            ("OWNER_ISSUE", owner, "OWNER", {"target_wallet_id": player}),
            ("RESERVE_FUND", owner, "OWNER", {"source_wallet_id": agent, "target_reserve": True}),
            ("BET_STAKE", player, "PLAYER", {"source_wallet_id": player, "target_reserve": True}),
            (
                "OWNER_TRANSFER",
                owner,
                "OWNER",
                {"source_wallet_id": owner, "target_wallet_id": owner},
            ),
        )
        for kind, actor, role, endpoints in cases:
            with self.subTest(kind=kind, endpoints=endpoints):
                with self.assertRaises(IntegrityError), self.connection.begin_nested():
                    self.operation(kind, actor, role, 10, **endpoints)
        self.issue(owner, 10)
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.connection.execute(
                insert(PointOperation.__table__).values(
                    kind="OWNER_ISSUE",
                    actor_account_id=owner,
                    actor_role="OWNER",
                    amount=10,
                    reason="schema test",
                    idempotency_key="duplicate",
                    request_fingerprint="a" * 64,
                    target_wallet_id=owner,
                )
            )
            self.connection.execute(
                insert(PointOperation.__table__).values(
                    kind="OWNER_ISSUE",
                    actor_account_id=owner,
                    actor_role="OWNER",
                    amount=10,
                    reason="schema test",
                    idempotency_key="duplicate",
                    request_fingerprint="a" * 64,
                    target_wallet_id=owner,
                )
            )


if __name__ == "__main__":
    unittest.main()
