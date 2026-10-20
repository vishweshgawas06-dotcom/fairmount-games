"""Single source of 'now' so time can be injected in tests and by the round scheduler."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)
