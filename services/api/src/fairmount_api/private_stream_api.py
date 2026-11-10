"""Private stream handshake: no token URLs, cached scope or replay authority."""

import uuid
from functools import partial

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.exc import SQLAlchemyError

from fairmount_api import private_stream
from fairmount_api.identity.http_boundary import (
    SESSION_COOKIE,
    RequestBoundaryUnavailable,
    _single_cookie,
)
from fairmount_api.identity.login_api import _direct_source
from fairmount_api.identity.session_validation import session_token_digest
from fairmount_api.resource_reads import ResourceUnavailable

router = APIRouter()
_HEADERS = {"Cache-Control": "no-store", "Vary": "Cookie", "X-Content-Type-Options": "nosniff"}


def _denied(status):
    return JSONResponse({"status": "unavailable"}, status_code=status, headers=_HEADERS)


def _open(request: Request, target=None):
    try:
        _direct_source(request, origin_required=False)
        token = _single_cookie(request, SESSION_COOKIE)
    except RequestBoundaryUnavailable:
        return _denied(401)
    except ValueError:
        return _denied(503)
    # EventSource's reconnect ID is informational only. Never use it to select
    # old private events; snapshots replace client state on every new connection.
    ids = request.headers.getlist("last-event-id")
    if (
        request.query_params
        or len(ids) > 1
        or (ids and (not ids[0].isascii() or not ids[0].isdigit() or len(ids[0]) > 10))
    ):
        return _denied(400)
    digest = session_token_digest(token)
    if digest is None:
        return _denied(401)
    read = partial(private_stream.load_snapshot, token, target)
    try:
        read()  # authorize before response headers, never emit this cached value
    except ResourceUnavailable:
        return _denied(401)
    except (SQLAlchemyError, private_stream.PrivateBackendUnavailable):
        return _denied(503)
    try:
        private_stream.capacity.enter(digest)
    except private_stream.PrivateCapacityUnavailable:
        return _denied(503)
    return StreamingResponse(
        private_stream.guarded_events(digest, read),
        media_type="text/event-stream",
        headers={**_HEADERS, "X-Accel-Buffering": "no"},
    )


@router.get("/api/v1/me/stream", tags=["private-events"], response_model=None)
def own_stream(request: Request):
    return _open(request)


@router.get(
    "/api/v1/players/{player_account_id}/stream", tags=["private-events"], response_model=None
)
def player_stream(request: Request, player_account_id: uuid.UUID):
    return _open(request, player_account_id)
