"""Strict bet-body schema tests; pure functions, no database or route."""

import unittest

from fairmount_api.roulette.bet_request import (
    MAX_STAKE,
    BetRequest,
    BetRequestInvalid,
    describe_bet_request,
    parse_bet_request,
)


class BetRequestSchemaTests(unittest.TestCase):
    def test_valid_body_returns_canonical_intent(self):
        parsed = parse_bet_request({"selection_key": "straight:17", "stake": 10})
        self.assertEqual(parsed, BetRequest(selection_key="straight:17", stake=10))

    def test_equivalent_selection_spellings_share_one_canonical_key(self):
        for raw in ("split:20-17", "SPLIT:17-20", "  split:17-20  "):
            with self.subTest(raw=raw):
                self.assertEqual(
                    parse_bet_request({"selection_key": raw, "stake": 5}).selection_key,
                    "split:17-20",
                )

    def test_unknown_missing_or_non_object_bodies_are_rejected(self):
        cases = (
            {},
            {"selection_key": "straight:17"},
            {"stake": 10},
            {"selection_key": "straight:17", "stake": 10, "round_id": "x"},
            {"selection_key": "straight:17", "stake": 10, "player_id": "x"},
            {"selection_key": "straight:17", "stake": 10, "stake ": 5},
            ["straight:17", 10],
            "straight:17",
            None,
        )
        for body in cases:
            with self.subTest(body=body), self.assertRaises(BetRequestInvalid):
                parse_bet_request(body)

    def test_stake_must_be_a_positive_valid_chip_multiple(self):
        for stake in (True, False, 10.0, "10", None, 0, -5, 4, 7, 12, MAX_STAKE + 1):
            with self.subTest(stake=stake), self.assertRaises(BetRequestInvalid):
                parse_bet_request({"selection_key": "straight:17", "stake": stake})

    def test_every_approved_chip_and_minimum_is_accepted(self):
        for stake in (5, 10, 50, 100, 500):
            with self.subTest(stake=stake):
                self.assertEqual(
                    parse_bet_request({"selection_key": "red", "stake": stake}).stake, stake
                )

    def test_invalid_or_oversized_selections_are_rejected(self):
        for selection in (
            "",
            "straight",
            "straight:37",
            "straight:07",
            "split:17-17",
            "unknown:1",
            "straight:17;drop",
            "x" * 65,
            17,
            None,
        ):
            with self.subTest(selection=selection), self.assertRaises(BetRequestInvalid):
                parse_bet_request({"selection_key": selection, "stake": 5})

    def test_describe_wrapper_matches_parser(self):
        body = {"selection_key": "black", "stake": 50}
        self.assertEqual(describe_bet_request(body), parse_bet_request(body))
        with self.assertRaises(BetRequestInvalid):
            describe_bet_request({"selection_key": "black"})

    def test_errors_never_echo_submitted_values(self):
        secret = "straight:17;leak-me"
        try:
            parse_bet_request({"selection_key": secret, "stake": 5})
        except BetRequestInvalid as exc:
            self.assertNotIn("leak-me", str(exc))
            self.assertNotIn("17", str(exc))


if __name__ == "__main__":
    unittest.main()
