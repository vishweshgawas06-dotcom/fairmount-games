"""Pure owner-approved POOL-01 arithmetic; not a betting/wallet integration test."""

import unittest
import uuid

from fairmount_api.reserve_coverage import (
    RoundExposure,
    required_reserve,
    reserve_can_accept,
)


def round_exposure(*, payouts=None, refund=0):
    return RoundExposure(tuple(payouts if payouts is not None else [0] * 37), refund)


class ReserveCoverageTests(unittest.TestCase):
    def test_payout_max_not_average_or_lowest_exposure(self) -> None:
        round_id = uuid.uuid4()
        payouts = [0] * 37
        payouts[0] = 350  # 10 straight-up at the approved total-return multiplier.
        payouts[17] = 20
        exposed = {round_id: round_exposure(payouts=payouts, refund=10)}
        self.assertEqual(required_reserve(exposed), 350)
        self.assertFalse(reserve_can_accept(339, 10, exposed))
        self.assertTrue(reserve_can_accept(340, 10, exposed))
        self.assertEqual(exposed[round_id].payout_by_number[0], 350)

    def test_void_refund_may_dominate_every_winning_number(self) -> None:
        round_id = uuid.uuid4()
        payouts = [15] * 37
        exposed = {round_id: round_exposure(payouts=payouts, refund=100)}
        self.assertEqual(required_reserve(exposed), 100)
        self.assertFalse(reserve_can_accept(94, 5, exposed))
        self.assertTrue(reserve_can_accept(95, 5, exposed))

    def test_independent_rounds_sum_maxima_not_max_of_shared_number(self) -> None:
        first = [0] * 37
        second = [0] * 37
        first[0], second[36] = 350, 250
        exposed = {
            uuid.uuid4(): round_exposure(payouts=first, refund=20),
            uuid.uuid4(): round_exposure(payouts=second, refund=300),
        }
        self.assertEqual(required_reserve(exposed), 650)
        self.assertFalse(reserve_can_accept(639, 10, exposed))
        self.assertTrue(reserve_can_accept(640, 10, exposed))
        self.assertEqual(required_reserve({}), 0)

    def test_invalid_shapes_fail_closed_and_do_not_accept_negative_points(self) -> None:
        with self.assertRaises(ValueError):
            round_exposure(payouts=[0] * 36)
        with self.assertRaises(ValueError):
            round_exposure(payouts=[0] * 38)
        with self.assertRaises(ValueError):
            round_exposure(payouts=[0] * 36 + [-1])
        with self.assertRaises(ValueError):
            round_exposure(payouts=[0] * 36 + [True])
        with self.assertRaises(ValueError):
            round_exposure(refund=-1)
        with self.assertRaises(ValueError):
            RoundExposure([0] * 37, 5)
        with self.assertRaises(ValueError):
            required_reserve({"unvalidated-round": round_exposure()})
        with self.assertRaises(ValueError):
            required_reserve({uuid.uuid4(): object()})
        for balance, stake in ((-1, 10), (True, 10), (0, 0), (0, -5), (0, 3.5)):
            with self.subTest(balance=balance, stake=stake):
                with self.assertRaises(ValueError):
                    reserve_can_accept(balance, stake, {})
        with self.assertRaises(ValueError):
            reserve_can_accept(1000, 5, {})
        with self.assertRaises(ValueError):
            reserve_can_accept(1000, 10, {uuid.uuid4(): round_exposure(refund=5)})


if __name__ == "__main__":
    unittest.main()
