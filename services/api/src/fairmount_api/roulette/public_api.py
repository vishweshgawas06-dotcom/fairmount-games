"""Read-only HTTP snapshot of the persisted round, never a bet/gameplay route.

No client input determines state or result. This endpoint has no private bets or
balances, and has no event/replay contract; D-08 realtime design remains open.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.exc import SQLAlchemyError

from fairmount_api.readiness import _configured_engine, schema_ready
from fairmount_api.roulette import public_stream
from fairmount_api.roulette.public_payload import encode_snapshot
from fairmount_api.roulette.public_snapshot import read_public_round_snapshot

router = APIRouter()
_NO_STORE = {"Cache-Control": "no-store"}


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
    return JSONResponse(encode_snapshot(snapshot), headers=_NO_STORE)


@router.get("/api/v1/roulette/stream", tags=["round"], response_model=None)
def current_round_stream() -> StreamingResponse | JSONResponse:
    """Stream the reveal-safe public snapshot; never a private or betting feed."""
    engine = _configured_engine()
    if engine is None:
        return JSONResponse({"status": "unavailable"}, status_code=503, headers=_NO_STORE)
    try:
        with engine.connect() as connection:
            if not schema_ready(connection):
                return JSONResponse({"status": "unavailable"}, status_code=503, headers=_NO_STORE)
    except SQLAlchemyError:
        return JSONResponse({"status": "unavailable"}, status_code=503, headers=_NO_STORE)
    try:
        public_stream.capacity.enter()
    except public_stream.StreamCapacityExceeded:
        return JSONResponse({"status": "unavailable"}, status_code=503, headers=_NO_STORE)
    return StreamingResponse(public_stream.guarded_stream(), headers=public_stream.stream_headers())
