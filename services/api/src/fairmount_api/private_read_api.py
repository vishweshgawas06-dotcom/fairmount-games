"""Opt-in direct-TLS private self-reads and authorized player-wallet read.

The client player ID is only a proposed target, never proof of access. Every
request rechecks the live session and current resource scope inside the read
transaction. Disabled/revoked sessions fail closed even with a saved cookie.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from fairmount_api.identity.http_boundary import (
    SESSION_COOKIE,
    RequestBoundaryUnavailable,
    _single_cookie,
)
from fairmount_api.identity.login_api import _direct_source
from fairmount_api.readiness import _configured_engine, schema_ready
from fairmount_api.resource_reads import (
    ResourceUnavailable,
    read_own_recent_bets,
    read_own_wallet,
    read_player_wallet,
)

router = APIRouter()
_PRIVATE_HEADERS = {
    "Cache-Control": "no-store",
    "Vary": "Cookie",
    "X-Content-Type-Options": "nosniff",
}


def _unavailable(status: int) -> JSONResponse:
    return JSONResponse({"status": "unavailable"}, status_code=status, headers=_PRIVATE_HEADERS)


@router.get("/api/v1/me/wallet", tags=["private"])
def my_wallet(request: Request) -> JSONResponse:
    """Commit the session touch before emitting this actor's own wallet balance."""
    try:
        _direct_source(request, origin_required=False)
        raw_token = _single_cookie(request, SESSION_COOKIE)
    except RequestBoundaryUnavailable:
        return _unavailable(401)
    except ValueError:
        return _unavailable(503)
    if request.query_params:
        return _unavailable(400)  # no client-provided account/assignment scope
    engine = _configured_engine()
    if engine is None:
        return _unavailable(503)
    try:
        with engine.begin() as connection:
            if not schema_ready(connection):
                return _unavailable(503)
            wallet = read_own_wallet(connection, raw_token)
    except ResourceUnavailable:
        return _unavailable(401)
    except SQLAlchemyError:
        return _unavailable(503)
    return JSONResponse(
        {"account_id": str(wallet.account_id), "balance": wallet.balance},
        headers=_PRIVATE_HEADERS,
    )


@router.get("/api/v1/players/{player_id}/wallet", tags=["private"])
def player_wallet(request: Request, player_id: str) -> JSONResponse:
    """Current player wallet for owner, assigned agent or the player themself.

    The URL ID is *not* authority; the data layer checks role, enabled state
    and current assignment again under locks before returning the balance.
    """
    try:
        _direct_source(request, origin_required=False)
        raw_token = _single_cookie(request, SESSION_COOKIE)
    except RequestBoundaryUnavailable:
        return _unavailable(401)
    except ValueError:
        return _unavailable(503)
    if request.query_params:
        return _unavailable(400)
    try:
        target = uuid.UUID(player_id)
        if str(target) != player_id:
            return _unavailable(404)  # one canonical UUID representation only
    except ValueError:
        return _unavailable(404)
    engine = _configured_engine()
    if engine is None:
        return _unavailable(503)
    try:
        with engine.begin() as connection:
            if not schema_ready(connection):
                return _unavailable(503)
            wallet = read_player_wallet(connection, raw_token, target)
    except ResourceUnavailable:
        return _unavailable(404)  # no existence/assignment disclosure
    except SQLAlchemyError:
        return _unavailable(503)
    return JSONResponse(
        {"account_id": str(wallet.account_id), "balance": wallet.balance},
        headers=_PRIVATE_HEADERS,
    )


@router.get("/api/v1/me/recent-bets", tags=["private"])
def my_recent_bets(request: Request) -> JSONResponse:
    """Latest 100 accepted bets for this enabled PLAYER session only."""
    try:
        _direct_source(request, origin_required=False)
        raw_token = _single_cookie(request, SESSION_COOKIE)
    except RequestBoundaryUnavailable:
        return _unavailable(401)
    except ValueError:
        return _unavailable(503)
    if request.query_params:
        return _unavailable(400)
    engine = _configured_engine()
    if engine is None:
        return _unavailable(503)
    try:
        with engine.begin() as connection:
            if not schema_ready(connection):
                return _unavailable(503)
            bets = read_own_recent_bets(connection, raw_token)
    except ResourceUnavailable:
        return _unavailable(401)
    except SQLAlchemyError:
        return _unavailable(503)
    return JSONResponse(
        {
            "bets": [
                {
                    "id": str(bet.id),
                    "round_id": str(bet.round_id),
                    "selection_key": bet.selection_key,
                    "accepted_stake": bet.accepted_stake,
                    "accepted_at": bet.accepted_at.isoformat(),
                }
                for bet in bets
            ]
        },
        headers=_PRIVATE_HEADERS,
    )
