"""Opt-in direct-TLS login/logout boundary; unavailable behind a proxy.

Never enable in the HTTP preview. A deployment must prove that ASGI scheme and
client peer are the real direct TLS connection (proxy headers disabled). Trusted
reverse-proxy client-IP handling is not approved; this endpoint fails closed by
default rather than trusting X-Forwarded-* for the failure-rate guard.
"""

from __future__ import annotations

import ipaddress
import json
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from fairmount_api.identity.auth_hmac_key import load_auth_hmac_key
from fairmount_api.identity.guarded_issuance import guarded_member_login, guarded_owner_login
from fairmount_api.identity.http_boundary import (
    RequestBoundaryUnavailable,
    _origin_host,
    _single_header,
    clear_session_cookies,
    require_same_origin_session,
    set_session_cookies,
)
from fairmount_api.identity.member_login import IssuedMemberSession
from fairmount_api.identity.mfa_keys import load_mfa_keyring
from fairmount_api.identity.owner_login import IssuedOwnerSession
from fairmount_api.identity.session_logout import revoke_presented_session
from fairmount_api.readiness import _configured_engine, schema_ready

router = APIRouter()
_NO_STORE = {"Cache-Control": "no-store"}


def _reply(status: int, label: str) -> JSONResponse:
    return JSONResponse({"status": label}, status_code=status, headers=_NO_STORE)


def _direct_source(request: Request, *, origin_required: bool = True) -> str:
    """Require a configured direct HTTPS peer and one exact browser origin.

    No forwarded header is accepted even if it appears to name a valid IP.
    Only deployment configuration can opt in; no dev/default bypass exists.
    """
    if os.environ.get("FAIRMOUNT_AUTH_EDGE_MODE") != "direct-tls":
        raise ValueError("Direct TLS auth not configured")
    origin = os.environ.get("FAIRMOUNT_PUBLIC_ORIGIN")
    host = _origin_host(origin)
    if request.scope.get("scheme") != "https":
        raise ValueError("Direct TLS is required")
    if any(
        request.headers.getlist(name)
        for name in (
            "forwarded",
            "x-forwarded-for",
            "x-forwarded-host",
            "x-forwarded-proto",
            "x-real-ip",
        )
    ):
        raise ValueError("Forwarded client identity is unsupported")
    if _single_header(request, "host").lower() != host:
        raise RequestBoundaryUnavailable("Request unavailable")
    if origin_required:
        if _single_header(request, "origin") != origin:
            raise RequestBoundaryUnavailable("Request unavailable")
    else:
        origins = request.headers.getlist("origin")
        if origins and (len(origins) != 1 or origins[0] != origin):
            raise RequestBoundaryUnavailable("Request unavailable")
        site = request.headers.getlist("sec-fetch-site")
        if site and (len(site) != 1 or site[0] not in ("same-origin", "none")):
            raise RequestBoundaryUnavailable("Request unavailable")
    client = request.client
    if client is None:
        raise ValueError("Transport peer unavailable")
    try:
        return str(ipaddress.ip_address(client.host))
    except ValueError as exc:
        raise ValueError("Transport peer unavailable") from exc


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate input field")
        result[key] = value
    return result


async def _credentials(request: Request) -> dict[str, str]:
    content_type = _single_header(request, "content-type").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise ValueError("Invalid request")
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > 4096:
            raise ValueError("Request too large")
        raw.extend(chunk)
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid request") from exc
    if not isinstance(payload, dict) or payload.get("role") not in ("OWNER", "AGENT", "PLAYER"):
        raise ValueError("Invalid request")
    required = (
        {"role", "identifier", "password", "factor_kind", "code"}
        if payload["role"] == "OWNER"
        else {"role", "identifier", "password"}
    )
    if set(payload) != required or any(not isinstance(value, str) for value in payload.values()):
        raise ValueError("Invalid request")
    if not 1 <= len(payload["identifier"]) <= 128 or not 1 <= len(payload["password"]) <= 128:
        raise ValueError("Invalid request")
    if payload["role"] == "OWNER" and (
        payload["factor_kind"] not in ("totp", "recovery") or not 1 <= len(payload["code"]) <= 64
    ):
        raise ValueError("Invalid request")
    return payload


@router.post("/api/v1/auth/login", tags=["auth"])
async def login(request: Request) -> JSONResponse:
    """Commit failure audit or successful issuance before setting cookies.

    Throttling and bad proof share one generic 401. Missing configuration or
    database is 503. Credentials, MFA codes and raw tokens never enter JSON.
    """
    try:
        source_ip = _direct_source(request)
    except RequestBoundaryUnavailable:
        return _reply(403, "unavailable")
    except ValueError:
        return _reply(503, "unavailable")
    try:
        payload = await _credentials(request)
    except ValueError:
        return _reply(400, "invalid_request")
    engine = _configured_engine()
    if engine is None:
        return _reply(503, "unavailable")
    try:
        pepper = load_auth_hmac_key()
        keyring = load_mfa_keyring() if payload["role"] == "OWNER" else None
    except ValueError:
        return _reply(503, "unavailable")
    try:
        with engine.begin() as connection:
            if not schema_ready(connection):
                return _reply(503, "unavailable")
            if payload["role"] == "OWNER":
                outcome = guarded_owner_login(
                    connection,
                    identifier=payload["identifier"],
                    password=payload["password"],
                    factor_kind=payload["factor_kind"],
                    code=payload["code"],
                    keyring=keyring,
                    source_ip=source_ip,
                    pepper=pepper,
                )
            else:
                outcome = guarded_member_login(
                    connection,
                    role=payload["role"],
                    identifier=payload["identifier"],
                    password=payload["password"],
                    source_ip=source_ip,
                    pepper=pepper,
                )
    except SQLAlchemyError:
        return _reply(503, "unavailable")
    if not outcome.allowed:
        return _reply(401, "denied")
    issued = outcome.value
    if not isinstance(issued, (IssuedMemberSession, IssuedOwnerSession)):
        raise RuntimeError("Guard did not issue a bound session")
    role = issued.role if isinstance(issued, IssuedMemberSession) else "OWNER"
    response = _reply(200, "authenticated")
    set_session_cookies(response, issued.token, role=role)
    return response


@router.post("/api/v1/auth/logout", tags=["auth"])
def logout(request: Request) -> JSONResponse:
    """CSRF-guarded, commit-before-clear bearer revocation in direct TLS mode.

    An already-absent or revoked token is idempotently acknowledged; no account
    existence or current-session details are disclosed. Never clear the cookie
    on DB failure before the revocation transaction can commit.
    """
    try:
        _direct_source(request)
        raw_token = require_same_origin_session(
            request, public_origin=os.environ["FAIRMOUNT_PUBLIC_ORIGIN"]
        )
    except RequestBoundaryUnavailable:
        return _reply(403, "unavailable")
    except (ValueError, KeyError):
        return _reply(503, "unavailable")
    engine = _configured_engine()
    if engine is None:
        return _reply(503, "unavailable")
    try:
        with engine.begin() as connection:
            if not schema_ready(connection):
                return _reply(503, "unavailable")
            revoke_presented_session(connection, raw_token)
    except SQLAlchemyError:
        return _reply(503, "unavailable")
    response = _reply(200, "signed_out")
    clear_session_cookies(response)
    return response
