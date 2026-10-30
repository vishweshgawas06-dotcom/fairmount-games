"""Strict request schema for a future player bet write (pure functions, no I/O).

An accepted body has exactly two fields. Anything else — unknown keys, wrong
types, non-canonical selections, out-of-range stakes — is rejected before any
database work. Selection keys are normalised so an idempotency fingerprint
cannot differ between equivalent spellings such as ``split:20-17`` and
``split:17-20``.

This module authorizes nothing; the caller still resolves the session and runs
reserve-locked admission inside its own transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fairmount_api.core.errors import InvalidSelection, InvalidStake
from fairmount_api.roulette.caps import validate_stake
from fairmount_api.roulette.catalogue import parse_selection_key

MAX_STAKE = 2**63 - 1
_ALLOWED_FIELDS = frozenset({"selection_key", "stake"})


class BetRequestInvalid(ValueError):
    """Generic schema rejection; never echoes the submitted value."""


@dataclass(frozen=True)
class BetRequest:
    """Canonical bet intent: one catalogue selection and one validated stake."""

    selection_key: str
    stake: int


def parse_bet_request(body: object) -> BetRequest:
    """Validate one decoded JSON body; reject anything that is not an exact intent."""
    if not isinstance(body, dict):
        raise BetRequestInvalid("Bet request unavailable")
    if set(body) != _ALLOWED_FIELDS:
        raise BetRequestInvalid("Bet request unavailable")  # missing or extra fields
    raw_selection = body["selection_key"]
    raw_stake = body["stake"]
    if isinstance(raw_stake, bool) or not isinstance(raw_stake, int):
        raise BetRequestInvalid("Bet request unavailable")
    if not 0 < raw_stake <= MAX_STAKE:
        raise BetRequestInvalid("Bet request unavailable")
    try:
        validate_stake(raw_stake)
        selection = parse_selection_key(raw_selection)
    except (InvalidStake, InvalidSelection) as exc:
        raise BetRequestInvalid("Bet request unavailable") from exc
    return BetRequest(selection_key=selection.key, stake=raw_stake)


def describe_bet_request(body: dict[str, Any]) -> BetRequest:
    """Typed convenience wrapper for callers that already hold a ``dict`` body."""
    if not isinstance(body, dict):
        raise BetRequestInvalid("Bet request unavailable")
    return parse_bet_request(body)
