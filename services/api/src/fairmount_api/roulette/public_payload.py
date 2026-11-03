"""Encoding for the public round snapshot; shared by the JSON and stream routes.

Only reveal-safe fields are encoded. Any field added here becomes public, so a
private bet, wallet, identity or RNG value must never reach this module.
"""

from __future__ import annotations

from fairmount_api.roulette.public_snapshot import RoundSnapshot


def encode_snapshot(snapshot: RoundSnapshot) -> dict:
    return {
        "observed_at": snapshot.observed_at.isoformat(),
        "round": None
        if snapshot.round_id is None
        else {
            "id": str(snapshot.round_id),
            "phase": snapshot.phase,
            "closes_at": snapshot.closes_at.isoformat() if snapshot.closes_at else None,
            "reveal_at": snapshot.reveal_at.isoformat() if snapshot.reveal_at else None,
            "winning_number": snapshot.winning_number,
        },
        "recent": [
            {
                "round_id": str(item.round_id),
                "state": item.state,
                "winning_number": item.winning_number,
            }
            for item in snapshot.recent
        ],
    }


__all__ = ["encode_snapshot"]
