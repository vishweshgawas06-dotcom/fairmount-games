"""Pure-domain tests: catalogue vs the owner-approved fixture, payouts, caps, config."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fairmount_api.core.errors import InvalidSelection, InvalidStake
from fairmount_api.roulette.caps import accepted_amount, validate_stake
from fairmount_api.roulette.catalogue import CATALOGUE, BetType, parse_selection_key
from fairmount_api.roulette.payout import MULTIPLIERS, total_payout

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "roulette_catalogue.json").read_text(encoding="utf-8")
)
INSIDE = FIXTURE["inside_selections"]
OUTSIDE = FIXTURE["outside_selections"]


def numbers_of(bet_type: BetType) -> set[tuple[int, ...]]:
    return {tuple(sorted(s.numbers)) for s in CATALOGUE.values() if s.bet_type is bet_type}


def as_set(rows: list[list[int]]) -> set[tuple[int, ...]]:
    return {tuple(sorted(r)) for r in rows}


class TestCatalogueMatchesApprovedFixture:
    def test_straight_ups(self):
        assert numbers_of(BetType.STRAIGHT) == as_set(INSIDE["straight_up"])

    def test_splits(self):
        assert numbers_of(BetType.SPLIT) == as_set(INSIDE["splits"]["all"])

    def test_streets(self):
        assert numbers_of(BetType.STREET) == as_set(INSIDE["streets"]["all"])

    def test_corners(self):
        assert numbers_of(BetType.CORNER) == as_set(INSIDE["corners"])

    def test_six_lines(self):
        assert numbers_of(BetType.SIX_LINE) == as_set(INSIDE["six_lines"])

    def test_first_four(self):
        assert numbers_of(BetType.FIRST_FOUR) == as_set(INSIDE["first_four"])

    def test_dozens_and_columns(self):
        for i in (1, 2, 3):
            assert CATALOGUE[f"dozen:{i}"].numbers == set(OUTSIDE["dozens"][f"dozen_{i}"])
            assert CATALOGUE[f"column:{i}"].numbers == set(OUTSIDE["columns"][f"column_{i}"])

    def test_even_money_sets(self):
        assert CATALOGUE["red"].numbers == set(FIXTURE["colors"]["red"])
        assert CATALOGUE["black"].numbers == set(FIXTURE["colors"]["black"])
        for name in ("odd", "even", "low", "high"):
            assert CATALOGUE[name].numbers == set(OUTSIDE[name])

    def test_counts_match_expected(self):
        counts = FIXTURE["expected_counts"]
        assert len(numbers_of(BetType.STRAIGHT)) == counts["straight_up"]
        assert len(numbers_of(BetType.SPLIT)) == counts["total_splits"]
        assert len(numbers_of(BetType.STREET)) == counts["total_streets"]
        assert len(numbers_of(BetType.CORNER)) == counts["generic_corners"]
        assert len(numbers_of(BetType.SIX_LINE)) == counts["six_lines"]

    def test_zero_is_excluded_from_outside_bets(self):
        outside = ("red", "black", "odd", "even", "low", "high")
        for key in (*outside, "dozen:1", "dozen:2", "dozen:3", "column:1", "column:2", "column:3"):
            assert 0 not in CATALOGUE[key].numbers

    def test_no_selection_key_duplicates_numbers_inconsistently(self):
        for key, sel in CATALOGUE.items():
            assert sel.key == key
            assert sel.numbers <= set(range(37))


class TestParseSelectionKey:
    def test_normalises_number_order_and_whitespace_and_case(self):
        assert parse_selection_key("split:20-17").key == "split:17-20"
        assert parse_selection_key("  Split:17-20 ").key == "split:17-20"
        assert parse_selection_key("corner:5-4-2-1").key == "corner:1-2-4-5"

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            None,
            17,
            "straight:37",
            "straight:-1",
            "straight:1.5",
            "straight:017",  # leading zeros are not canonical
            "straight:07",
            "straight:",
            "straight",
            "split:1-5",  # diagonal / non-adjacent
            "split:1-1",
            "split:0-4",
            "street:1-2-4",
            "street:0-1-3",
            "corner:0-1-2-3",  # first four is its own bet type
            "corner:1-2-3-4",
            "six_line:0-1-2-3-4-5",
            "six_line:2-3-4-5-6-7",
            "dozen:0",
            "dozen:4",
            "column:",
            "red:1",
            "purple",
            "first_four:0-1-2-3",
            "straight:1; DROP TABLE bets",
            "straight:" + "1-" * 40,
            "straight:\u0661\u0667",  # non-ASCII digits
        ],
    )
    def test_rejects_anything_not_in_catalogue(self, bad):
        with pytest.raises(InvalidSelection):
            parse_selection_key(bad)

    def test_every_catalogue_key_round_trips(self):
        for key, sel in CATALOGUE.items():
            assert parse_selection_key(key) is sel


class TestPayouts:
    @pytest.mark.parametrize(
        ("key", "winning", "expected"),
        [
            ("straight:17", 17, 350),
            ("split:17-20", 20, 170),
            ("street:1-2-3", 2, 110),
            ("corner:1-2-4-5", 5, 80),
            ("six_line:1-2-3-4-5-6", 6, 50),
            ("first_four", 0, 80),
            ("dozen:1", 12, 20),
            ("column:3", 36, 20),
            ("red", 1, 10),
            ("black", 2, 10),
            ("odd", 35, 10),
            ("even", 36, 10),
            ("low", 18, 10),
            ("high", 19, 10),
        ],
    )
    def test_ten_coin_win_credits_total_payout(self, key, winning, expected):
        assert total_payout(10, parse_selection_key(key), winning) == expected

    def test_zero_beats_all_outside_bets(self):
        for key in ("red", "black", "odd", "even", "low", "high", "dozen:1", "column:1"):
            assert total_payout(100, parse_selection_key(key), 0) == 0

    def test_losing_bet_pays_nothing(self):
        assert total_payout(10, parse_selection_key("straight:17"), 18) == 0

    def test_every_bet_type_has_a_multiplier(self):
        assert set(MULTIPLIERS) == set(BetType)

    def test_rejects_out_of_range_inputs(self):
        sel = parse_selection_key("red")
        with pytest.raises(ValueError, match="between 0 and 36"):
            total_payout(10, sel, 37)
        with pytest.raises(ValueError, match="positive"):
            total_payout(0, sel, 1)


class TestStakeAndCaps:
    @pytest.mark.parametrize("ok", [5, 10, 15, 500, 2000])
    def test_valid_stakes(self, ok):
        assert validate_stake(ok) == ok

    @pytest.mark.parametrize("bad", [0, -5, 1, 4, 6, 12, 5.0, "10", None, True, False])
    def test_invalid_stakes(self, bad):
        with pytest.raises(InvalidStake):
            validate_stake(bad)

    def test_accepts_full_amount_when_room(self):
        assert accepted_amount(500, [2000]) == 500

    def test_cap_limited_partial_acceptance(self):
        assert accepted_amount(1000, [500]) == 500  # spec example: 1,500 already on a number

    def test_smallest_remaining_cap_wins_for_split(self):
        assert accepted_amount(300, [200, 50]) == 50

    def test_rounds_down_to_multiple_of_five(self):
        assert accepted_amount(100, [7]) == 5
        assert accepted_amount(100, [4]) == 0  # PA-05 defensive invariant

    def test_zero_or_negative_remaining_means_nothing_accepted(self):
        assert accepted_amount(100, [0]) == 0
        assert accepted_amount(100, [-5]) == 0

    @pytest.mark.parametrize("bad", [0, -5, True, 5.0, 6])
    def test_unvalidated_requested_stake_fails_closed(self, bad):
        with pytest.raises(InvalidStake):
            accepted_amount(bad, [2000])

    @pytest.mark.parametrize("capacities", [[], [True], [5.0], [100, "50"]])
    def test_missing_or_malformed_capacities_fail_closed(self, capacities):
        with pytest.raises(ValueError, match="remaining cap"):
            accepted_amount(100, capacities)
