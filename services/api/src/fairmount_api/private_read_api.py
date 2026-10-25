"""Opt-in direct-TLS private self-wallet HTTP projection; never client-ID scoped.

No role can read another account through this path. The authenticated actor and
wallet target are derived from the same live database session, not a query/body
parameter. Disabled/revoked sessions fail closed even with a saved cookie.
"""

from __future__ import annotations

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
from fairmount_api.resource_reads import ResourceUnavailable, read_own_wallet

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
