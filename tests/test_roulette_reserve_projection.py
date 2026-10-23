"""Pure integration of owner-approved roulette payouts with POOL-01 coverage."""

import unittest
import uuid

from fairmount_api.core.errors import InvalidSelection, InvalidStake
from fairmount_api.reserve_coverage import (
    RoundExposure,
    project_round_exposure,
    required_reserve,
    reserve_can_accept,
)
from fairmount_api.roulette.catalogue import parse_selection_key
from fairmount_api.roulette.payout import total_payout


class RouletteReserveProjectionTests(unittest.TestCase):
    def test_every_outcome_matches_independent_sum_of_payouts(self) -> None:
        bets = [
            ("straight:0", 10),
            ("split:20-17", 20),
            ("red", 50),
            ("dozen:1", 100),
            ("first_four", 5),
            ("straight:0", 5),  # duplicate records add up, not overwritten
        ]
        projection = project_round_exposure(bets)
        self.assertEqual(projection.full_void_refund, 190)
        self.assertEqual(len(projection.payout_by_number), 37)
        for number in range(37):
            expected = sum(
                total_payout(amount, parse_selection_key(key), number) for key, amount in bets
            )
            with self.subTest(number=number):
                self.assertEqual(projection.payout_by_number[number], expected)
        self.assertEqual(projection.payout_by_number[0], 15 * 35 + 5 * 8)
        self.assertEqual(projection.payout_by_number[17], 20 * 17)
        self.assertEqual(projection.obligation, 565)

    def test_candidate_is_counted_once_in_refund_and_worst_case(self) -> None:
        rid = uuid.uuid4()
        prior = [("straight:17", 10)]
        candidate = ("straight:17", 5)
        before = project_round_exposure(prior)
        after = project_round_exposure([*prior, candidate])
        self.assertEqual(before.payout_by_number[17], 350)
        self.assertEqual(after.payout_by_number[17], 525)
        self.assertEqual(after.full_void_refund, 15)
        self.assertEqual(required_reserve({rid: after}), 525)
        # The candidate stake reaches the reserve only on successful admission.
        self.assertFalse(reserve_can_accept(519, 5, {rid: after}))
        self.assertTrue(reserve_can_accept(520, 5, {rid: after}))
        self.assertEqual(prior, [("straight:17", 10)])

    def test_full_void_refund_may_dominate_and_rounds_sum(self) -> None:
        first, second = uuid.uuid4(), uuid.uuid4()
        refund_dominates = project_round_exposure([("red", 100), ("black", 100)])
        payout_dominates = project_round_exposure([("straight:36", 10)])
        self.assertEqual(refund_dominates.obligation, 200)
        self.assertEqual(payout_dominates.obligation, 350)
        unsettled = {first: refund_dominates, second: payout_dominates}
        self.assertEqual(required_reserve(unsettled), 550)
        self.assertFalse(reserve_can_accept(539, 10, unsettled))
        self.assertTrue(reserve_can_accept(540, 10, unsettled))

    def test_invalid_selection_and_stake_fail_closed(self) -> None:
        for key in ("straight:37", "split:1-5", "straight:01", "purple", None):
            with self.subTest(key=key), self.assertRaises(InvalidSelection):
                project_round_exposure([(key, 10)])
        for stake in (0, -5, 1, 5.0, True, "10"):
            with self.subTest(stake=stake), self.assertRaises(InvalidStake):
                project_round_exposure([("red", stake)])

    def test_no_bets_is_zero_exposure_not_a_valid_candidate(self) -> None:
        empty = project_round_exposure([])
        self.assertEqual(empty, RoundExposure((0,) * 37, 0))
        with self.assertRaises(ValueError):
            reserve_can_accept(100, 5, {uuid.uuid4(): empty})

    def test_total_payout_rejects_bool_float_and_noninteger_winner(self) -> None:
        selection = parse_selection_key("straight:1")
        for stake, winner in ((True, 1), (5.0, 1), (5, True), (5, 1.0), (5, -1)):
            with self.subTest(stake=stake, winner=winner), self.assertRaises(ValueError):
                total_payout(stake, selection, winner)


if __name__ == "__main__":
    unittest.main()
