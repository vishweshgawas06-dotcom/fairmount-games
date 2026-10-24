"""Read-only HTTP snapshot of the persisted round, never a bet/gameplay route.

No client input determines state or result. This endpoint has no private bets or
balances, and has no event/replay contract; D-08 realtime design remains open.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from fairmount_api.readiness import _configured_engine, schema_ready
from fairmount_api.roulette.public_snapshot import RoundSnapshot, read_public_round_snapshot

router = APIRouter()
_NO_STORE = {"Cache-Control": "no-store"}


def _encode(snapshot: RoundSnapshot) -> dict:
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


@router.get("/api/v1/roulette/round", tags=["round"])
def current_round() -> JSONResponse:
    """Return no private data and never fabricate a missing result or void."""
    engine = _configured_engine()
    if engine is None:
        return JSONResponse({"status": "unavailable"}, status_code=503, headers=_NO_STORE)
    try:
        with engine.connect() as connection:
            if not schema_ready(connection):
                return JSONResponse({"status": "unavailable"}, status_code=503, headers=_NO_STORE)
            snapshot = read_public_round_snapshot(connection)
    except SQLAlchemyError:
        # No connection, SQL or credential details are suitable for public HTTP.
        return JSONResponse({"status": "unavailable"}, status_code=503, headers=_NO_STORE)
    return JSONResponse(_encode(snapshot), headers=_NO_STORE)
