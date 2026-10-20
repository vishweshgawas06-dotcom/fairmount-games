"""Specification-only tests for the canonical roulette catalogue fixture.

Run from the repository root:
    python -m unittest discover -s tests -v

These tests do not implement or test bet acceptance, wallets, payouts, or the betting engine.
"""
import json
import unittest
from pathlib import Path

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "roulette_catalogue.json"


def sorted_set(values):
    return sorted(values)


class RouletteCatalogueFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.inside = cls.fixture["inside_selections"]

    def test_pockets_and_straight_up_count(self):
        self.assertEqual(self.fixture["pockets"], list(range(37)))
        self.assertEqual(self.inside["straight_up"], [[n] for n in range(37)])
        self.assertEqual(len(self.inside["straight_up"]), 37)

    def test_red_black_sets_are_disjoint_and_cover_one_to_36(self):
        red = self.fixture["colors"]["red"]
        black = self.fixture["colors"]["black"]
        self.assertEqual(
            red, [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
        )
        self.assertEqual(
            black, [2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35]
        )
        self.assertEqual(len(red), 18)
        self.assertEqual(len(black), 18)
        self.assertEqual(len(set(red)), 18)
        self.assertEqual(len(set(black)), 18)
        self.assertTrue(set(red).isdisjoint(black))
        self.assertNotIn(0, red + black)
        self.assertEqual(sorted(red + black), list(range(1, 37)))
        self.assertEqual(self.fixture["colors"]["green"], [0])


    def test_outside_selection_sets(self):
        outside = self.fixture["outside_selections"]
        self.assertEqual(outside["dozens"]["dozen_1"], list(range(1, 13)))
        self.assertEqual(outside["dozens"]["dozen_2"], list(range(13, 25)))
        self.assertEqual(outside["dozens"]["dozen_3"], list(range(25, 37)))
        self.assertEqual(outside["columns"]["column_1"], list(range(1, 37, 3)))
        self.assertEqual(outside["columns"]["column_2"], list(range(2, 37, 3)))
        self.assertEqual(outside["columns"]["column_3"], list(range(3, 37, 3)))
        self.assertEqual(outside["low"], list(range(1, 19)))
        self.assertEqual(outside["high"], list(range(19, 37)))
        self.assertEqual(outside["odd"], list(range(1, 37, 2)))
        self.assertEqual(outside["even"], list(range(2, 37, 2)))

    def test_split_catalogue_counts_and_geometry(self):
        splits = self.inside["splits"]
        expected_horizontal = []
        for row_start in range(1, 37, 3):
            expected_horizontal.extend([[row_start, row_start + 1], [row_start + 1, row_start + 2]])
        expected_vertical = []
        for row_start in range(1, 34, 3):
            expected_vertical.extend([
                [row_start, row_start + 3],
                [row_start + 1, row_start + 4],
                [row_start + 2, row_start + 5],
            ])
        self.assertEqual(splits["horizontal"], expected_horizontal)
        self.assertEqual(splits["vertical"], expected_vertical)
        self.assertEqual(splits["zero"], [[0, 1], [0, 2], [0, 3]])
        self.assertEqual(len(splits["horizontal"]), 24)
        self.assertEqual(len(splits["vertical"]), 33)
        self.assertEqual(len(splits["zero"]), 3)
        self.assertEqual(len(splits["all"]), 60)
        self.assertEqual(
            splits["all"], expected_horizontal + expected_vertical + [[0, 1], [0, 2], [0, 3]]
        )

    def test_street_catalogue(self):
        expected_numbered = [[n, n + 1, n + 2] for n in range(1, 37, 3)]
        expected_zero = [[0, 1, 2], [0, 2, 3]]
        self.assertEqual(self.inside["streets"]["numbered"], expected_numbered)
        self.assertEqual(self.inside["streets"]["zero_adjacent"], expected_zero)
        self.assertEqual(self.inside["streets"]["all"], expected_numbered + expected_zero)
        self.assertEqual(len(self.inside["streets"]["all"]), 14)

    def test_generic_corners_are_exactly_numbered_grid_2x2_blocks(self):
        rows = [[n, n + 1, n + 2] for n in range(1, 37, 3)]
        expected = []
        for row_index in range(11):
            for col_index in range(2):
                expected.append(sorted_set([
                    rows[row_index][col_index],
                    rows[row_index][col_index + 1],
                    rows[row_index + 1][col_index],
                    rows[row_index + 1][col_index + 1],
                ]))
        self.assertEqual(self.inside["corners"], expected)
        self.assertEqual(len(self.inside["corners"]), 22)
        self.assertNotIn([0, 1, 2, 3], self.inside["corners"])

    def test_six_lines_and_first_four(self):
        rows = [[n, n + 1, n + 2] for n in range(1, 37, 3)]
        expected_six_lines = [rows[i] + rows[i + 1] for i in range(11)]
        self.assertEqual(self.inside["six_lines"], expected_six_lines)
        self.assertEqual(len(self.inside["six_lines"]), 11)
        self.assertTrue(all(0 not in line for line in self.inside["six_lines"]))
        self.assertEqual(self.inside["first_four"], [[0, 1, 2, 3]])

    def test_expected_count_summary_matches_fixture_data(self):
        counts = self.fixture["expected_counts"]
        self.assertEqual(counts, {
            "straight_up": 37,
            "horizontal_splits": 24,
            "vertical_splits": 33,
            "zero_splits": 3,
            "total_splits": 60,
            "numbered_streets": 12,
            "zero_adjacent_streets": 2,
            "total_streets": 14,
            "generic_corners": 22,
            "six_lines": 11,
            "first_four": 1,
        })
        self.assertEqual(
            counts["horizontal_splits"] + counts["vertical_splits"] + counts["zero_splits"],
            counts["total_splits"],
        )
        self.assertEqual(
            counts["numbered_streets"] + counts["zero_adjacent_streets"],
            counts["total_streets"],
        )


if __name__ == "__main__":
    unittest.main()
