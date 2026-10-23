"""Private rate-guarded adapters for owner/member proof and owner step-up.

Only future request handlers may call these adapters; they must commit both
success and generic denial, never invoke unguarded issuers over HTTP, and supply
a trusted peer IP and restricted, separate authentication HMAC secret.
"""

from __future__ import annotations

from sqlalchemy import Connection

from fairmount_api.identity.auth_attempts import AuthAttemptOutcome, guarded_authentication
from fairmount_api.identity.member_login import MemberLoginUnavailable, issue_member_session
from fairmount_api.identity.mfa_keys import MFAKeyring
from fairmount_api.identity.owner_login import OwnerLoginUnavailable, issue_owner_session
from fairmount_api.identity.owner_mfa_verification import OwnerMFAProofUnavailable
from fairmount_api.identity.owner_step_up import step_up_owner_session


def guarded_owner_login(
    connection: Connection,
    *,
    identifier: str,
    password: str,
    factor_kind: str,
    code: str,
    keyring: MFAKeyring,
    source_ip: str,
    pepper: bytes,
) -> AuthAttemptOutcome:
    """Generic denial covers wrong owner label, password and MFA alike."""
    return guarded_authentication(
        connection,
        surface="OWNER_LOGIN",
        identifier=identifier,
        source_ip=source_ip,
        pepper=pepper,
        authenticate=lambda conn: issue_owner_session(
            conn, identifier, password, factor_kind, code, keyring
        ),
        denied_by=(OwnerLoginUnavailable,),
    )


def guarded_member_login(
    connection: Connection,
    *,
    role: str,
    identifier: str,
    password: str,
    source_ip: str,
    pepper: bytes,
) -> AuthAttemptOutcome:
    """Rate guard includes declared role; actual fixed-ID/credential check is DB-side."""
    if role not in ("AGENT", "PLAYER"):
        raise ValueError("Unsupported login surface")
    return guarded_authentication(
        connection,
        surface="MEMBER_LOGIN",
        identifier=f"{role}:{identifier}",
        source_ip=source_ip,
        pepper=pepper,
        authenticate=lambda conn: issue_member_session(conn, role, identifier, password),
        denied_by=(MemberLoginUnavailable,),
    )


def guarded_owner_step_up(
    connection: Connection,
    *,
    raw_token: str,
    factor_kind: str,
    code: str,
    keyring: MFAKeyring,
    source_ip: str,
    pepper: bytes,
) -> AuthAttemptOutcome:
    """MFA throttling is bound to sole owner and trusted source, not raw token."""
    return guarded_authentication(
        connection,
        surface="OWNER_MFA",
        identifier="owner",
        source_ip=source_ip,
        pepper=pepper,
        authenticate=lambda conn: step_up_owner_session(
            conn, raw_token, factor_kind, code, keyring
        ),
        denied_by=(OwnerMFAProofUnavailable,),
    )
