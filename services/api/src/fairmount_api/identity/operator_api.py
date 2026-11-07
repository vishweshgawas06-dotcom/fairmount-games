"""Opt-in direct-TLS owner writes, with atomic non-secret replay receipts.

Disabled behind a proxy. A provision response discloses its setup secret only
on first success; replay returns the stored account reference, never a secret.
A lost first response needs a separately authorized credential reissue flow.
"""

from __future__ import annotations

import hashlib
import json
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import insert, select
from sqlalchemy.exc import SQLAlchemyError

from fairmount_api.db.models import OperatorWriteReceipt
from fairmount_api.identity.account_admin import (
    AccountAdminUnavailable,
    assign_player,
    resolve_agent_id,
    resolve_member_id,
    resolve_player_id,
    set_account_enabled,
    unassign_player,
)
from fairmount_api.identity.auth_hmac_key import load_auth_hmac_key
from fairmount_api.identity.http_boundary import RequestBoundaryUnavailable
from fairmount_api.identity.login_api import _direct_source
from fairmount_api.identity.member_activation import (
    MemberActivationUnavailable,
    reissue_pending_member_secret,
)
from fairmount_api.identity.provisioning import (
    ProvisioningUnavailable,
    _require_owner,
    provision_agent,
    provision_player,
)
from fairmount_api.identity.write_boundary import GameplayWriteUnavailable, require_gameplay_write
from fairmount_api.readiness import _configured_engine, schema_ready
from fairmount_api.roulette.write_limits import guard_gameplay_write

router = APIRouter()
_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Vary": "Cookie",
    "X-Content-Type-Options": "nosniff",
}


class OperatorRequestInvalid(ValueError):
    """Strict body-schema denial; never reflect client input."""


class OperatorReplayConflict(ValueError):
    """The key already committed a different command."""


_DENIALS = (
    ProvisioningUnavailable,
    AccountAdminUnavailable,
    MemberActivationUnavailable,
    OperatorRequestInvalid,
    OperatorReplayConflict,
)


def _reply(status: int, label: str = "unavailable", *, retry_after: int = 0) -> JSONResponse:
    headers = dict(_HEADERS)
    if retry_after > 0:
        headers["Retry-After"] = str(min(retry_after, 3600))
    return JSONResponse({"status": label}, status_code=status, headers=headers)


def _validate(kind: str, body: dict) -> None:
    required = {
        "agent": set(),
        "player": {"username"},
        "assign": {"username", "agent_id"},
        "unassign": {"username"},
        "status": {"identifier", "enabled"},
        "reissue": {"identifier"},
    }[kind]
    optional = {"agent_id"} if kind == "agent" else set()
    if not required <= body.keys() or body.keys() - required - optional:
        raise OperatorRequestInvalid("Invalid request")
    for name, value in body.items():
        if name == "enabled":
            if type(value) is not bool:
                raise OperatorRequestInvalid("Invalid request")
        elif not isinstance(value, str) or not 1 <= len(value) <= 128:
            raise OperatorRequestInvalid("Invalid request")


def _action(connection, token, kind, body) -> dict:
    if kind in ("agent", "player"):
        member = (
            provision_agent(connection, token, agent_id=body.get("agent_id"))
            if kind == "agent"
            else provision_player(connection, token, username=body["username"])
        )
        return {
            "status": "created",
            "account_id": str(member.account_id),
            "agent_id" if kind == "agent" else "username": member.login_id,
            "secret": member.secret,
            "secret_expires_at": member.expires_at.isoformat(),
        }
    if kind == "assign":
        assignment = assign_player(
            connection,
            token,
            player_id=resolve_player_id(connection, body["username"]),
            agent_id=resolve_agent_id(connection, body["agent_id"]),
        )
        return {"status": "assigned", "assignment_id": str(assignment)}
    if kind == "unassign":
        unassign_player(
            connection, token, player_id=resolve_player_id(connection, body["username"])
        )
        return {"status": "unassigned"}
    if kind == "reissue":
        account_id, role = resolve_member_id(connection, body["identifier"])
        member = reissue_pending_member_secret(connection, token, account_id=account_id)
        return {
            "status": "setup_secret_reissued",
            "account_id": str(member.account_id),
            "role": role,
            "secret": member.secret,
            "secret_expires_at": member.expires_at.isoformat(),
        }
    account_id, role = resolve_member_id(connection, body["identifier"])
    status = set_account_enabled(connection, token, account_id=account_id, enabled=body["enabled"])
    return {"status": status.lower(), "role": role}


def _execute(connection, token, key, kind, body) -> tuple[int, dict]:
    # Owner lock serializes concurrent commands, including duplicate requests.
    # Authenticate before resolving identifiers OR reading a replay receipt.
    owner_id = _require_owner(connection, token)
    _validate(kind, body)
    digest = hashlib.sha256(
        json.dumps([kind, body], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    receipt = connection.execute(
        select(OperatorWriteReceipt.request_digest, OperatorWriteReceipt.response).where(
            OperatorWriteReceipt.owner_account_id == owner_id,
            OperatorWriteReceipt.request_key == key,
        )
    ).one_or_none()
    if receipt is not None:
        if receipt.request_digest != digest:
            raise OperatorReplayConflict("Request conflict")
        return 200, {**receipt.response, "replayed": True}
    response = _action(connection, token, kind, body)
    # Never persist the setup secret, even in the idempotency store. The client
    # must distinguish an acknowledged replay from first-time secret delivery.
    stored = {name: value for name, value in response.items() if name != "secret"}
    connection.execute(
        insert(OperatorWriteReceipt.__table__).values(
            owner_account_id=owner_id,
            request_key=key,
            request_digest=digest,
            response=stored,
        )
    )
    return (201 if kind in ("agent", "player") else 200), {**response, "replayed": False}


async def _dispatch(request: Request, kind: str) -> JSONResponse:
    try:
        source_ip = _direct_source(request, origin_required=True)
    except RequestBoundaryUnavailable:
        return _reply(401)
    except (KeyError, ValueError):
        return _reply(503)
    try:
        write = await require_gameplay_write(
            request, public_origin=os.environ["FAIRMOUNT_PUBLIC_ORIGIN"]
        )
    except GameplayWriteUnavailable:
        return _reply(401)
    except (KeyError, ValueError):
        return _reply(503)
    engine = _configured_engine()
    if engine is None:
        return _reply(503)
    try:
        pepper = load_auth_hmac_key()
    except (ValueError, OSError):
        return _reply(503)
    try:
        with engine.begin() as connection:
            if not schema_ready(connection):
                return _reply(503)
            outcome = guard_gameplay_write(
                connection,
                write.session_token,
                source_ip=source_ip,
                pepper=pepper,
                write=lambda scoped: _execute(
                    scoped, write.session_token, write.idempotency_key, kind, write.body
                ),
                denied_by=_DENIALS,
            )
    except SQLAlchemyError:
        return _reply(503)
    if outcome.throttled:
        return _reply(429, "throttled", retry_after=outcome.retry_after)
    if not outcome.allowed:
        if outcome.denial is OperatorRequestInvalid:
            return _reply(400, "invalid_request")
        if outcome.denial is OperatorReplayConflict:
            return _reply(409, "conflict")
        return _reply(403, "denied")
    status, payload = outcome.value
    return JSONResponse(payload, status_code=status, headers=dict(_HEADERS))


@router.post("/api/v1/operator/agents", tags=["operator"])
async def create_agent(request: Request) -> JSONResponse:
    """Create an agent; disclose the setup secret only on first success."""
    return await _dispatch(request, "agent")


@router.post("/api/v1/operator/players", tags=["operator"])
async def create_player(request: Request) -> JSONResponse:
    """Create an unassigned player; disclose the setup secret on first success."""
    return await _dispatch(request, "player")


@router.post("/api/v1/operator/assignments", tags=["operator"])
async def assign(request: Request) -> JSONResponse:
    return await _dispatch(request, "assign")


@router.post("/api/v1/operator/assignments/remove", tags=["operator"])
async def remove_assignment(request: Request) -> JSONResponse:
    return await _dispatch(request, "unassign")


@router.post("/api/v1/operator/accounts/status", tags=["operator"])
async def account_status(request: Request) -> JSONResponse:
    return await _dispatch(request, "status")


@router.post("/api/v1/operator/accounts/setup-secret", tags=["operator"])
async def reissue_setup_secret(request: Request) -> JSONResponse:
    """Rotate a still-pending member credential; never changes an active password."""
    return await _dispatch(request, "reissue")
