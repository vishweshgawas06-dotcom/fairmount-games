"""Opt-in direct-TLS player bet write; disabled unless explicitly configured.

The route is an adapter only. It requires a direct HTTPS peer with no forwarding
headers, the same-origin gameplay-write envelope, a strict bet body schema, and
then runs the existing reserve-serialized admission inside one committed
transaction. There is no partial-stake acceptance, no proxy mode and no
unauthenticated access.
"""

from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from fairmount_api.identity.auth_hmac_key import load_auth_hmac_key
from fairmount_api.identity.http_boundary import RequestBoundaryUnavailable
from fairmount_api.identity.login_api import _direct_source
from fairmount_api.identity.write_boundary import (
    GameplayWriteUnavailable,
    require_gameplay_write,
)
from fairmount_api.readiness import _configured_engine, schema_ready
from fairmount_api.roulette.admission import BetReplayConflict, BetUnavailable, place_bet
from fairmount_api.roulette.bet_request import BetRequestInvalid, parse_bet_request
from fairmount_api.roulette.write_limits import guard_gameplay_write

router = APIRouter()
_WRITE_HEADERS = {
    "Cache-Control": "no-store",
    "Vary": "Cookie",
    "X-Content-Type-Options": "nosniff",
}


def _reply(status: int, label: str = "unavailable", *, retry_after: int = 0) -> JSONResponse:
    headers = dict(_WRITE_HEADERS)
    if retry_after > 0:
        headers["Retry-After"] = str(min(retry_after, 3600))
    return JSONResponse({"status": label}, status_code=status, headers=headers)


@router.post("/api/v1/rounds/{round_id}/bets", tags=["gameplay"])
async def place_player_bet(request: Request, round_id: str) -> JSONResponse:
    """Accept one idempotent player stake, or fail closed without detail.

    The client-supplied round UUID is only a proposed target: the database
    rechecks session role, round state, cutoff, wallet balance, caps and reserve
    coverage under the documented lock order.
    """
    try:
        source_ip = _direct_source(request, origin_required=True)
    except RequestBoundaryUnavailable:
        return _reply(401)
    except (KeyError, ValueError):
        return _reply(503)  # direct TLS or canonical origin not configured
    origin = os.environ["FAIRMOUNT_PUBLIC_ORIGIN"]
    try:
        write = await require_gameplay_write(request, public_origin=origin)
    except GameplayWriteUnavailable:
        return _reply(401)
    except ValueError:
        return _reply(503)
    try:
        target = uuid.UUID(round_id)
        if str(target) != round_id:
            return _reply(404)
    except ValueError:
        return _reply(404)
    try:
        bet_request = parse_bet_request(write.body)
    except BetRequestInvalid:
        return _reply(400)
    engine = _configured_engine()
    if engine is None:
        return _reply(503)
    try:
        pepper = load_auth_hmac_key()
    except ValueError:
        return _reply(503)  # the restricted HMAC key file is required
    try:
        with engine.begin() as connection:
            if not schema_ready(connection):
                return _reply(503)
            # Attempt counting and admission commit together; a denial still
            # spends budget so a rejection flood cannot bypass the window.
            outcome = guard_gameplay_write(
                connection,
                write.session_token,
                source_ip=source_ip,
                pepper=pepper,
                write=lambda active: place_bet(
                    active,
                    write.session_token,
                    round_id=target,
                    selection_key=bet_request.selection_key,
                    requested=bet_request.stake,
                    idempotency_key=str(write.idempotency_key),
                ),
                denied_by=(BetUnavailable,),
            )
    except SQLAlchemyError:
        return _reply(503)
    except ValueError:
        return _reply(503)
    if outcome.throttled:
        return _reply(429, retry_after=outcome.retry_after)
    if not outcome.allowed:
        if outcome.denial is BetReplayConflict:
            return _reply(409, "conflict")  # same key, different request
        return _reply(409)  # generic: closed round, cap, balance or stale session
    accepted = outcome.value
    return JSONResponse(
        {
            "bet_id": str(accepted.bet_id),
            "requested": accepted.requested,
            "accepted": accepted.accepted,
            "unaccepted": accepted.unaccepted,
            "replayed": accepted.replayed,
        },
        headers=_WRITE_HEADERS,
    )
