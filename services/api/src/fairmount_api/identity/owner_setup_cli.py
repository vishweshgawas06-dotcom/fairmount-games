"""Owner-only *local development* setup terminal; never a remotely callable route.

Example: FAIRMOUNT_DB_NAME=fairmount_dev python -m fairmount_api.identity.owner_setup_cli init
The owner personally controls the terminal and deployment shell. Secrets appear only
after a successful DB commit; terminal scrollback is sensitive and must be protected.
This local-only database adapter is not a production deployment configuration.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from collections.abc import Sequence
from typing import TextIO

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from fairmount_api.identity.mfa_keys import load_mfa_keyring
from fairmount_api.identity.owner_activation import activate_initial_owner
from fairmount_api.identity.owner_bootstrap import bootstrap_owner, reissue_pending_owner_secret
from fairmount_api.identity.owner_mfa_enrollment import (
    begin_owner_mfa_enrollment,
    confirm_owner_mfa_enrollment,
)
from infrastructure.local_db_url import local_database_url

COMMANDS = ("init", "reissue", "activate", "enroll", "confirm")


def _secret_prompt(message: str, error_stream: TextIO) -> str:
    """Read from a terminal without echoing; no secret may be passed as a CLI argument."""
    return getpass.getpass(message, stream=error_stream)


def main(
    argv: Sequence[str] | None = None,
    *,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
    error_stream: TextIO | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="Local owner setup (no dashboard access)")
    parser.add_argument("command", choices=COMMANDS)
    args = parser.parse_args(argv)
    incoming = input_stream if input_stream is not None else sys.stdin
    outgoing = output_stream if output_stream is not None else sys.stdout
    errors = error_stream if error_stream is not None else sys.stderr
    if not all(stream.isatty() for stream in (incoming, outgoing, errors)):
        errors.write("Refusing non-interactive owner setup; use an owner-controlled terminal.\n")
        return 2
    if os.environ.get("FAIRMOUNT_DB_NAME") != "fairmount_dev":
        errors.write("Select the local fairmount_dev database explicitly.\n")
        return 2

    engine = None
    committed = False
    try:
        if args.command == "activate":
            token = _secret_prompt("Initial owner secret: ", errors)
            password = _secret_prompt("New permanent password: ", errors)
            confirmation = _secret_prompt("Repeat permanent password: ", errors)
            if password != confirmation:
                raise ValueError("Password confirmation does not match")
        elif args.command == "confirm":
            code = _secret_prompt("Current authenticator code: ", errors)
        if args.command in {"enroll", "confirm"}:
            keyring = load_mfa_keyring()
        engine = create_engine(local_database_url(test=False), poolclass=NullPool)
        # Nothing is written to the terminal while the transaction remains open.
        with engine.begin() as connection:
            if args.command == "init":
                issued = bootstrap_owner(connection)
            elif args.command == "reissue":
                issued = reissue_pending_owner_secret(connection)
            elif args.command == "activate":
                activate_initial_owner(connection, token, password)
            elif args.command == "enroll":
                pending_factor = begin_owner_mfa_enrollment(connection, keyring)
            else:
                confirmed = confirm_owner_mfa_enrollment(connection, code, keyring)
        committed = True
        if args.command in {"init", "reissue"}:
            outgoing.write("Initial owner secret (shown once; expires in 24 hours):\n")
            outgoing.write(f"{issued.secret}\n")
        elif args.command == "activate":
            outgoing.write("Password set. Enroll and confirm MFA before any owner access.\n")
        elif args.command == "enroll":
            outgoing.write("Authenticator seed (shown once; keep it private):\n")
            outgoing.write(f"{pending_factor.secret}\n")
        else:
            outgoing.write("Recovery codes (shown once; store offline; each is single-use):\n")
            for recovery_code in confirmed.recovery_codes:
                outgoing.write(f"{recovery_code}\n")
            outgoing.write("MFA enrolled. No owner login/session route exists yet.\n")
        outgoing.flush()
        return 0
    except (ValueError, SQLAlchemyError, OSError, EOFError):
        # SQLAlchemy errors can include SQL bind parameters; never print or log them.
        if committed:
            errors.write(
                "Database committed, but terminal delivery may have failed. "
                "Do not retry blindly; protect any partial output.\n"
            )
        else:
            errors.write("Owner setup failed before commit; no secret was displayed.\n")
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
