"""Pure identifier validation and generation for future account provisioning.

Store only canonical lowercase login IDs. Agent IDs displayed to humans are uppercase;
neither kind of ID is a password, session token, or evidence of authorization.
"""

from __future__ import annotations

import re
import secrets

PLAYER_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,31}")
AGENT_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
AGENT_PATTERN = re.compile(rf"AGT-[{AGENT_ALPHABET}]{{10}}")
RESERVED_PLAYER_NAMES = frozenset({"admin", "owner", "support", "system", "root"})


def canonical_player_username(value: str) -> str:
    """Validate the approved ASCII format and return a lowercase username."""
    if not isinstance(value, str) or not PLAYER_PATTERN.fullmatch(value):
        raise ValueError("Invalid player username format")
    canonical = value.lower()
    if canonical in RESERVED_PLAYER_NAMES or canonical.startswith("agt-"):
        raise ValueError("Reserved player username")
    return canonical


def canonical_agent_id(value: str) -> str:
    """Validate a generated-style Agent ID and return its lowercase DB form."""
    if (
        not isinstance(value, str)
        or not value.isascii()
        or not AGENT_PATTERN.fullmatch(value.upper())
    ):
        raise ValueError("Invalid Agent ID format")
    return value.lower()


def generate_agent_id() -> str:
    """Generate a non-secret public Agent ID; DB uniqueness must handle collisions."""
    return "AGT-" + "".join(secrets.choice(AGENT_ALPHABET) for _ in range(10))
