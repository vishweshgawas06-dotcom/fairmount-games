"""Canonical legal-position catalogue for single-zero European roulette.

Source of truth: docs/project-plan/roulette/LEGAL_POSITION_CATALOGUE_REVIEW.md (owner-approved
2026-10-14). Selections are validated here, never from client labels or coordinates.

A selection is addressed by a canonical string key, for example ``straight:17``,
``split:17-20``, ``street:0-1-2``, ``dozen:2`` or ``red``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from fairmount_api.core.errors import InvalidSelection

MAX_KEY_LENGTH = 64


class BetType(StrEnum):
    STRAIGHT = "straight"
    SPLIT = "split"
    STREET = "street"
    CORNER = "corner"
    SIX_LINE = "six_line"
    FIRST_FOUR = "first_four"
    DOZEN = "dozen"
    COLUMN = "column"
    RED = "red"
    BLACK = "black"
    ODD = "odd"
    EVEN = "even"
    LOW = "low"
    HIGH = "high"


# Fixed canonical colours for the standard European wheel (must not be inferred).
RED = frozenset({1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36})
BLACK = frozenset({2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35})

_NUMBERED_TYPES = {
    BetType.STRAIGHT,
    BetType.SPLIT,
    BetType.STREET,
    BetType.CORNER,
    BetType.SIX_LINE,
}


@dataclass(frozen=True, slots=True)
class Selection:
    bet_type: BetType
    key: str
    numbers: frozenset[int]

    @property
    def uses_number_cap(self) -> bool:
        """Straight-up and split bets share the per-number exposure cap."""
        return self.bet_type in (BetType.STRAIGHT, BetType.SPLIT)


def _numbered_key(bet_type: BetType, numbers: tuple[int, ...]) -> str:
    return f"{bet_type.value}:" + "-".join(str(n) for n in numbers)


def _build_catalogue() -> dict[str, Selection]:
    catalogue: dict[str, Selection] = {}

    def add(bet_type: BetType, key: str, numbers: frozenset[int]) -> None:
        if key in catalogue:  # pragma: no cover - guards against catalogue bugs
            raise RuntimeError(f"duplicate catalogue key {key}")
        catalogue[key] = Selection(bet_type, key, numbers)

    def add_numbered(bet_type: BetType, numbers: tuple[int, ...]) -> None:
        add(bet_type, _numbered_key(bet_type, numbers), frozenset(numbers))

    for n in range(37):
        add_numbered(BetType.STRAIGHT, (n,))

    for row in range(12):  # horizontal splits within each three-number row
        first = 3 * row + 1
        add_numbered(BetType.SPLIT, (first, first + 1))
        add_numbered(BetType.SPLIT, (first + 1, first + 2))
    for n in range(1, 34):  # vertical splits between adjacent rows
        add_numbered(BetType.SPLIT, (n, n + 3))
    for n in (1, 2, 3):  # zero splits
        add_numbered(BetType.SPLIT, (0, n))

    for row in range(12):
        first = 3 * row + 1
        add_numbered(BetType.STREET, (first, first + 1, first + 2))
    add_numbered(BetType.STREET, (0, 1, 2))
    add_numbered(BetType.STREET, (0, 2, 3))

    for row in range(11):  # 2x2 blocks in the numbered grid only
        for col in range(2):
            a = 3 * row + 1 + col
            add_numbered(BetType.CORNER, (a, a + 1, a + 3, a + 4))

    for row in range(11):
        first = 3 * row + 1
        add_numbered(BetType.SIX_LINE, tuple(range(first, first + 6)))

    add(BetType.FIRST_FOUR, "first_four", frozenset({0, 1, 2, 3}))

    for i in (1, 2, 3):
        add(BetType.DOZEN, f"dozen:{i}", frozenset(range(12 * (i - 1) + 1, 12 * i + 1)))
        column = frozenset(n for n in range(1, 37) if (n - 1) % 3 == i - 1)
        add(BetType.COLUMN, f"column:{i}", column)

    add(BetType.RED, "red", RED)
    add(BetType.BLACK, "black", BLACK)
    add(BetType.ODD, "odd", frozenset(n for n in range(1, 37) if n % 2 == 1))
    add(BetType.EVEN, "even", frozenset(n for n in range(1, 37) if n % 2 == 0))
    add(BetType.LOW, "low", frozenset(range(1, 19)))
    add(BetType.HIGH, "high", frozenset(range(19, 37)))
    return catalogue


CATALOGUE: dict[str, Selection] = _build_catalogue()


def parse_selection_key(raw: object) -> Selection:
    """Validate and normalise a client-supplied selection key.

    Number order never matters (``split:20-17`` equals ``split:17-20``). Anything that is not an
    exact catalogue position is rejected with :class:`InvalidSelection`.
    """
    if not isinstance(raw, str) or not raw or len(raw) > MAX_KEY_LENGTH:
        raise InvalidSelection()
    key = raw.strip().lower()
    head, sep, tail = key.partition(":")
    try:
        bet_type = BetType(head)
    except ValueError:
        raise InvalidSelection() from None

    if bet_type in _NUMBERED_TYPES:
        if not sep or not tail:
            raise InvalidSelection()
        parts = tail.split("-")
        # Strict canonical spelling: ASCII digits only, no leading zeros ("07" is rejected).
        if not all(p.isascii() and p.isdigit() and p == str(int(p)) for p in parts):
            raise InvalidSelection()
        numbers = [int(p) for p in parts]
        if len(set(numbers)) != len(numbers):
            raise InvalidSelection()
        key = _numbered_key(bet_type, tuple(sorted(numbers)))
    elif bet_type in (BetType.DOZEN, BetType.COLUMN):
        if not sep or tail not in {"1", "2", "3"}:
            raise InvalidSelection()
        key = f"{bet_type.value}:{tail}"
    else:
        if sep:
            raise InvalidSelection()
        key = bet_type.value

    selection = CATALOGUE.get(key)
    if selection is None:
        raise InvalidSelection()
    return selection
