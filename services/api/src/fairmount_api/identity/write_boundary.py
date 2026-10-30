"""Gameplay-write request contract for *future* betting and funding routes.

No gameplay write route is exposed. This module only proves that an unsafe
request carries one same-origin session, a matching double-submit CSRF value,
one bounded JSON object and a stable idempotency key. It issues no authority:
the caller must still resolve the session and re-authorize the resource in its
own database transaction, and must persist the idempotency key with the write.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from starlette.requests import Request

from fairmount_api.identity.http_boundary import (
    RequestBoundaryUnavailable,
    require_same_origin_session,
)

MAX_WRITE_BYTES = 4096
_MEDIA_TYPE = "application/json"
_IDEMPOTENCY_HEADER = "idempotency-key"
_LENGTH = re.compile(r"[0-9]{1,9}\Z", re.ASCII)
_SAFE_FETCH_SITES = frozenset({"same-origin", "none"})
_FORBIDDEN_ENCODING_HEADERS = ("transfer-encoding", "content-encoding")


class GameplayWriteUnavailable(RequestBoundaryUnavailable):
    """Generic write denial; never reflect a header, body or token value."""


@dataclass(frozen=True)
class GameplayWriteRequest:
    """Validated envelope only; the body schema belongs to the specific route."""

    session_token: str = field(repr=False)
    idempotency_key: uuid.UUID
    body: dict[str, Any]


def _single_header(request: Request, name: str) -> str:
    values = request.headers.getlist(name)
    if len(values) != 1 or not values[0]:
        raise GameplayWriteUnavailable("Write unavailable")
    return values[0]


def _json_media_type(value: str) -> bool:
    """Accept exactly ``application/json`` with at most one explicit UTF-8 charset."""
    media, separator, parameter = value.partition(";")
    if media.strip().lower() != _MEDIA_TYPE:
        return False
    if not separator:
        return True
    name, separator, charset = parameter.partition("=")
    if not separator or name.strip().lower() != "charset":
        return False
    return charset.strip().strip('"').lower() in {"utf-8", "utf8"}


def _idempotency_key(value: str) -> uuid.UUID:
    """Normalize any accepted UUID spelling so duplicates share one persisted key."""
    try:
        parsed = uuid.UUID(value.strip())
    except (ValueError, AttributeError) as exc:
        raise GameplayWriteUnavailable("Write unavailable") from exc
    if parsed.int == 0:
        raise GameplayWriteUnavailable("Write unavailable")  # never a real key
    return parsed


def _pairs_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    body: dict[str, Any] = {}
    for key, value in pairs:
        if key in body:
            raise GameplayWriteUnavailable("Write unavailable")
        body[key] = value
    return body


def _reject_constant(_value: str) -> Any:
    raise GameplayWriteUnavailable("Write unavailable")  # NaN/Infinity are not JSON


async def _bounded_body(request: Request, declared: int, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            raise GameplayWriteUnavailable("Write unavailable")
        chunks.append(chunk)
    body = b"".join(chunks)
    if len(body) != declared:
        raise GameplayWriteUnavailable("Write unavailable")  # no smuggling ambiguity
    return body


async def require_gameplay_write(
    request: Request, *, public_origin: str, max_bytes: int = MAX_WRITE_BYTES
) -> GameplayWriteRequest:
    """Validate one unsafe gameplay write; never authorize or persist anything.

    Denials are deliberately indistinguishable. The returned session token is
    still untrusted until the caller resolves it against PostgreSQL and repeats
    live role/assignment/resource checks inside the write transaction.
    """
    if not isinstance(max_bytes, int) or not 0 < max_bytes <= MAX_WRITE_BYTES:
        raise ValueError("max_bytes must be a positive bounded integer")
    if request.method != "POST":
        raise GameplayWriteUnavailable("Write unavailable")  # creates only; no PUT/PATCH
    try:
        session_token = require_same_origin_session(request, public_origin=public_origin)
    except RequestBoundaryUnavailable as exc:
        # One denial type at this boundary: handlers cannot branch on the cause.
        raise GameplayWriteUnavailable("Write unavailable") from exc
    if request.query_params:
        raise GameplayWriteUnavailable("Write unavailable")
    if not _json_media_type(_single_header(request, "content-type")):
        raise GameplayWriteUnavailable("Write unavailable")
    declared = _single_header(request, "content-length")
    if _LENGTH.fullmatch(declared) is None:
        raise GameplayWriteUnavailable("Write unavailable")
    length = int(declared)
    if length > max_bytes:
        raise GameplayWriteUnavailable("Write unavailable")
    for header in _FORBIDDEN_ENCODING_HEADERS:
        if request.headers.getlist(header):
            raise GameplayWriteUnavailable("Write unavailable")
    fetch_sites = request.headers.getlist("sec-fetch-site")
    if fetch_sites and (len(fetch_sites) != 1 or fetch_sites[0] not in _SAFE_FETCH_SITES):
        raise GameplayWriteUnavailable("Write unavailable")
    key = _idempotency_key(_single_header(request, _IDEMPOTENCY_HEADER))
    raw = await _bounded_body(request, length, max_bytes)
    try:
        body = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs_without_duplicates,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise GameplayWriteUnavailable("Write unavailable") from exc
    if not isinstance(body, dict):
        raise GameplayWriteUnavailable("Write unavailable")
    return GameplayWriteRequest(session_token=session_token, idempotency_key=key, body=body)
