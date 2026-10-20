"""Typed application errors with stable machine-readable codes.

Every rejection a client can see maps to one of these classes. The ``code`` is part of the
public contract and must not change; ``message`` is human-readable and safe to display.
"""

from __future__ import annotations


class FairMountError(Exception):
    """Base class for all expected, client-visible errors."""

    code = "internal_error"
    http_status = 500

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message()
        super().__init__(self.message)

    @classmethod
    def default_message(cls) -> str:
        return "An unexpected error occurred."


class InvalidSelection(FairMountError):
    code = "invalid_selection"
    http_status = 422

    @classmethod
    def default_message(cls) -> str:
        return "That selection is not a valid position on the roulette table."


class InvalidStake(FairMountError):
    code = "invalid_stake"
    http_status = 422

    @classmethod
    def default_message(cls) -> str:
        return "Stake must be a whole number of at least 5, in multiples of 5."


class BettingClosed(FairMountError):
    code = "betting_closed"
    http_status = 409

    @classmethod
    def default_message(cls) -> str:
        return "Betting is closed for this round."


class InsufficientBalance(FairMountError):
    code = "insufficient_balance"
    http_status = 409

    @classmethod
    def default_message(cls) -> str:
        return "Your balance is too low for this bet."


class CapExceeded(FairMountError):
    code = "cap_exceeded"
    http_status = 409

    @classmethod
    def default_message(cls) -> str:
        return "The table limit for this position has been reached."


class RoundNotFound(FairMountError):
    code = "round_not_found"
    http_status = 404

    @classmethod
    def default_message(cls) -> str:
        return "Round not found."


class AccountNotFound(FairMountError):
    code = "account_not_found"
    http_status = 404

    @classmethod
    def default_message(cls) -> str:
        return "Account not found."


class InvalidRoundState(FairMountError):
    code = "invalid_round_state"
    http_status = 409

    @classmethod
    def default_message(cls) -> str:
        return "That action is not allowed in the round's current state."


class IdempotencyConflict(FairMountError):
    code = "idempotency_conflict"
    http_status = 409

    @classmethod
    def default_message(cls) -> str:
        return "This idempotency key was already used for a different request."


class InvalidAdjustment(FairMountError):
    code = "invalid_adjustment"
    http_status = 422

    @classmethod
    def default_message(cls) -> str:
        return "A non-zero whole-number amount and a written reason are required."


class TemporaryFailure(FairMountError):
    """A retryable infrastructure problem (e.g. repeated deadlock). Safe to retry."""

    code = "temporarily_unavailable"
    http_status = 503

    @classmethod
    def default_message(cls) -> str:
        return "The service is busy. Please try again."


class InvalidRequest(FairMountError):
    code = "invalid_request"
    http_status = 422

    @classmethod
    def default_message(cls) -> str:
        return "The request is not valid."
