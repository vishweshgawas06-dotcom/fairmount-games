"""Reusable same-origin cookie/CSRF boundary for *future* authenticated routes.

This module does not issue sessions or expose an HTTP login. Future handlers
must call the request guard AND the private transaction-scoped authorization
service, then commit before setting a server-issued token cookie. No proxy/IP
headers are trusted here; source-IP validation needs separate deployment review.
"""

from __future__ import annotations

import hmac
import re
import secrets
from urllib.parse import urlsplit

from fastapi import Request, Response

from fairmount_api.identity.session_validation import session_token_digest

SESSION_COOKIE = "__Host-fairmount_session"
CSRF_COOKIE = "__Host-fairmount_csrf"
CSRF_HEADER = "x-csrf-token"
_TOKEN_SHAPE = re.compile(r"[A-Za-z0-9_-]{43}\Z", re.ASCII)
_ROLE_MAX_AGE = {"OWNER": 8 * 3600, "AGENT": 12 * 3600, "PLAYER": 24 * 3600}


class RequestBoundaryUnavailable(ValueError):
    """Generic denial: never reflect a cookie, token, origin or header value."""


def _origin_host(configured_origin: str) -> str:
    """Require one explicit canonical HTTPS origin; never infer from forwarded headers."""
    if not isinstance(configured_origin, str):
        raise ValueError("A canonical HTTPS public origin must be configured")
    try:
        url = urlsplit(configured_origin)
        port = url.port  # reject malformed ports before comparing the configured Host
    except ValueError as exc:
        raise ValueError("A canonical HTTPS public origin must be configured") from exc
    if (
        url.scheme != "https"
        or not url.hostname
        or port == 0
        or not url.netloc
        or url.username is not None
        or url.password is not None
        or url.path
        or url.query
        or url.fragment
        or configured_origin != f"https://{url.netloc}"
    ):
        raise ValueError("A canonical HTTPS public origin must be configured")
    return url.netloc.lower()


def _single_header(request: Request, name: str) -> str:
    values = request.headers.getlist(name)
    if len(values) != 1 or not values[0]:
        raise RequestBoundaryUnavailable("Request unavailable")
    return values[0]


def _single_cookie(request: Request, name: str) -> str:
    # Starlette's cookie parser can collapse duplicate names. Reject ambiguity
    # BEFORE parsing instead of letting the first/last duplicate win.
    found = []
    for header in request.headers.getlist("cookie"):
        if len(header) > 8192:
            raise RequestBoundaryUnavailable("Request unavailable")
        for part in header.split(";"):
            label, separator, value = part.strip().partition("=")
            if label == name:
                if not separator:
                    raise RequestBoundaryUnavailable("Request unavailable")
                found.append(value)
    if len(found) != 1 or _TOKEN_SHAPE.fullmatch(found[0]) is None:
        raise RequestBoundaryUnavailable("Request unavailable")
    return found[0]


def require_same_origin_session(request: Request, *, public_origin: str) -> str:
    """Verify unsafe request Origin, Host, session cookie and double-submit CSRF.

    Only call on mutating HTTPS routes. The return value is an *untrusted*
    bearer token until resolve_session()/resource authorization has run in the
    caller's database transaction. The CSRF cookie is not an auth credential.
    """
    host = _origin_host(public_origin)  # configuration error fails closed
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        raise RequestBoundaryUnavailable("Request unavailable")
    origin = _single_header(request, "origin")
    if origin != public_origin or _single_header(request, "host").lower() != host:
        raise RequestBoundaryUnavailable("Request unavailable")
    raw_token = _single_cookie(request, SESSION_COOKIE)
    if session_token_digest(raw_token) is None:
        raise RequestBoundaryUnavailable("Request unavailable")
    csrf_cookie = _single_cookie(request, CSRF_COOKIE)
    csrf_header = _single_header(request, CSRF_HEADER)
    if _TOKEN_SHAPE.fullmatch(csrf_header) is None or not hmac.compare_digest(
        csrf_cookie, csrf_header
    ):
        raise RequestBoundaryUnavailable("Request unavailable")
    return raw_token


def set_session_cookies(response: Response, raw_token: str, *, role: str) -> str:
    """Set host-only, HTTPS-only auth and JS-readable CSRF cookies on success.

    Call only after the issuer's transaction has COMMITTED. Cookie lifetime is
    capped by role; PostgreSQL remains authoritative for revocation/expiry.
    """
    if session_token_digest(raw_token) is None or role not in _ROLE_MAX_AGE:
        raise ValueError("Invalid session issue context")
    csrf = secrets.token_urlsafe(32)
    max_age = _ROLE_MAX_AGE[role]
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        max_age=max_age,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=max_age,
        path="/",
        secure=True,
        httponly=False,
        samesite="strict",
    )
    return csrf


def clear_session_cookies(response: Response) -> None:
    """Expire both cookies on a future logout response, regardless of DB state."""
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="strict")
    response.delete_cookie(CSRF_COOKIE, path="/", secure=True, httponly=False, samesite="strict")
