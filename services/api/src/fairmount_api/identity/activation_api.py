"""Opt-in direct-TLS member setup; no ambient session authority or auto-login."""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from fairmount_api.identity.auth_attempts import guarded_authentication
from fairmount_api.identity.auth_hmac_key import load_auth_hmac_key
from fairmount_api.identity.http_boundary import RequestBoundaryUnavailable, _single_header
from fairmount_api.identity.login_api import _direct_source, _unique_object
from fairmount_api.identity.member_activation import MemberActivationUnavailable, activate_member
from fairmount_api.identity.write_boundary import _json_media_type
from fairmount_api.readiness import _configured_engine, schema_ready

router = APIRouter()
_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff"}


def _reply(status: int, label: str) -> JSONResponse:
    return JSONResponse({"status": label}, status_code=status, headers=_HEADERS)


async def _payload(request: Request) -> dict[str, str]:
    if request.query_params or any(
        request.headers.getlist(name)
        for name in (
            "content-encoding",
            "transfer-encoding",
        )
    ):
        raise ValueError("Invalid request")
    if not _json_media_type(_single_header(request, "content-type")):
        raise ValueError("Invalid request")
    length = _single_header(request, "content-length")
    if not length.isascii() or not length.isdecimal() or not 1 <= len(length) <= 9:
        raise ValueError("Invalid request")
    declared = int(length)
    if declared > 4096:
        raise ValueError("Invalid request")
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > 4096:
            raise ValueError("Invalid request")
        raw.extend(chunk)
    if len(raw) != declared:
        raise ValueError("Invalid request")
    payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    if (
        not isinstance(payload, dict)
        or set(payload) != {"role", "identifier", "secret", "new_password"}
        or any(not isinstance(value, str) for value in payload.values())
        or payload["role"] not in {"AGENT", "PLAYER"}
        or not 1 <= len(payload["identifier"]) <= 32
        or not 1 <= len(payload["secret"]) <= 256
        or not 1 <= len(payload["new_password"]) <= 128
    ):
        raise ValueError("Invalid request")
    return payload


@router.post("/api/v1/auth/activate", tags=["auth"])
async def activate(request: Request) -> JSONResponse:
    """Consume a temporary credential, with failure budgets before Argon2.

    No cookie/session is issued. The fixed owner login can never use this route.
    Proof failures, expired/used secrets, disabled/missing targets, weak passwords
    and throttling share the same 401; database/configuration errors are 503.
    """
    try:
        source_ip = _direct_source(request)
    except RequestBoundaryUnavailable:
        return _reply(403, "unavailable")
    except ValueError:
        return _reply(503, "unavailable")
    try:
        payload = await _payload(request)
    except (ValueError, UnicodeError):
        return _reply(400, "invalid_request")
    engine = _configured_engine()
    if engine is None:
        return _reply(503, "unavailable")
    try:
        pepper = load_auth_hmac_key()
    except (ValueError, OSError):
        return _reply(503, "unavailable")
    try:
        with engine.begin() as connection:
            if not schema_ready(connection):
                return _reply(503, "unavailable")
            outcome = guarded_authentication(
                connection,
                surface="MEMBER_ACTIVATION",
                identifier=f"{payload['role']}:{payload['identifier']}",
                source_ip=source_ip,
                pepper=pepper,
                authenticate=lambda scoped: activate_member(scoped, **payload),
                denied_by=(MemberActivationUnavailable,),
            )
    except SQLAlchemyError:
        return _reply(503, "unavailable")
    return _reply(200, "activated") if outcome.allowed else _reply(401, "denied")
