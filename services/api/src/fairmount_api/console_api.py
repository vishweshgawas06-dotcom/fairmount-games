"""Direct-TLS-only operator context, roster and administrative history."""

import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from fairmount_api.console_reads import decode_cursor, read_context, read_history, read_members
from fairmount_api.identity.http_boundary import (
    SESSION_COOKIE,
    RequestBoundaryUnavailable,
    _single_cookie,
)
from fairmount_api.identity.login_api import _direct_source
from fairmount_api.readiness import _configured_engine, schema_ready
from fairmount_api.resource_reads import ResourceUnavailable

router = APIRouter()
_HEADERS = {"Cache-Control": "no-store", "Vary": "Cookie", "X-Content-Type-Options": "nosniff"}


def _reply(status, body=None):
    return JSONResponse(
        body if body is not None else {"status": "unavailable"},
        status_code=status,
        headers=_HEADERS,
    )


def _read(request, projection, cursor=None):
    try:
        _direct_source(request, origin_required=False)
        token = _single_cookie(request, SESSION_COOKIE)
    except RequestBoundaryUnavailable:
        return _reply(401)
    except ValueError:
        return _reply(503)
    params = list(request.query_params.multi_items())
    after = None
    if params:
        if cursor is None or len(params) != 1 or params[0][0] != "after":
            return _reply(400)
        try:
            after = cursor(params[0][1])
        except (ValueError, TypeError):
            return _reply(400)
    engine = _configured_engine()
    if engine is None:
        return _reply(503)
    try:
        with engine.begin() as connection:
            if not schema_ready(connection):
                return _reply(503)
            payload = (
                projection(connection, token, after) if cursor else projection(connection, token)
            )
    except ResourceUnavailable:
        return _reply(401)
    except SQLAlchemyError:
        return _reply(503)
    return _reply(200, payload)


def _uuid_cursor(value):
    if len(value) != 36:
        raise ValueError("Invalid cursor")
    parsed = uuid.UUID(value)
    if str(parsed) != value:
        raise ValueError("Invalid cursor")
    return parsed


@router.get("/api/v1/console/context", tags=["console"])
def context(request: Request):
    return _read(request, read_context)


@router.get("/api/v1/console/members", tags=["console"])
def members(request: Request):
    return _read(request, read_members, _uuid_cursor)


@router.get("/api/v1/console/history", tags=["console"])
def history(request: Request):
    return _read(request, read_history, decode_cursor)
