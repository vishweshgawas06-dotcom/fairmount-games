"""Committed direct-TLS login → self-read → logout across separate DB connections.

Runs only against the disposable, migrated CI test database. Successful auth
writes immutable audit records, so do not point this test at a live database.
"""

import os
import unittest
import uuid
from unittest.mock import patch

from fairmount_api.db.models import (
    Account,
    AccountCredential,
    AccountSession,
    PrivateIdentity,
)
from fairmount_api.identity.credentials import hash_password
from fairmount_api.identity.http_boundary import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE
from fairmount_api.identity.session_validation import session_token_digest
from fairmount_api.main import app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, insert, select, update

from infrastructure.local_db_url import local_database_url

ORIGIN = "https://game.example"
PASSWORD = "test-only long private passphrase"
PEPPER = b"test-only-hmac-separate-from-mfa!"
CONFIG = {"FAIRMOUNT_AUTH_EDGE_MODE": "direct-tls", "FAIRMOUNT_PUBLIC_ORIGIN": ORIGIN}
WALLET = "/api/v1/me/wallet"
HISTORY = "/api/v1/me/recent-bets"


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "Disposable PostgreSQL test DB required"
)
class CommittedHTTPSessionFlowTests(unittest.TestCase):
    def test_login_read_logout_and_revocation_across_committed_connections(self):
        engine = create_engine(local_database_url(test=True))
        # Unique fixture: this disposable test DB is destroyed by the CI job.
        # Immutable auth events/wallet accounting deliberately forbid teardown
        # by deleting the live-style account after its session is issued.
        name = "p" + uuid.uuid4().hex[:24]
        try:
            with engine.begin() as connection:
                account_id = connection.execute(
                    insert(Account.__table__).values(role="PLAYER").returning(Account.id)
                ).scalar_one()
                other_player = connection.execute(
                    insert(Account.__table__).values(role="PLAYER").returning(Account.id)
                ).scalar_one()
                connection.execute(
                    insert(PrivateIdentity.__table__).values(
                        account_id=account_id, login_kind="PLAYER", login_identifier=name
                    )
                )
                connection.execute(
                    insert(AccountCredential.__table__).values(
                        account_id=account_id,
                        initial_secret_issued_at=func.now(),
                        initial_secret_consumed_at=func.now(),
                        password_hash=hash_password(PASSWORD),
                        password_changed_at=func.now(),
                    )
                )
            client = TestClient(app, base_url=ORIGIN, client=("203.0.113.98", 50400))
            with (
                patch.dict("os.environ", CONFIG),
                patch("fairmount_api.identity.login_api._configured_engine", return_value=engine),
                patch("fairmount_api.private_read_api._configured_engine", return_value=engine),
                patch("fairmount_api.identity.login_api.load_auth_hmac_key", return_value=PEPPER),
            ):
                login = client.post(
                    "/api/v1/auth/login",
                    headers={"Origin": ORIGIN},
                    json={"role": "PLAYER", "identifier": name, "password": PASSWORD},
                )
                self.assertEqual(
                    (login.status_code, login.json()), (200, {"status": "authenticated"})
                )
                token = client.cookies[SESSION_COOKIE]
                csrf = client.cookies[CSRF_COOKIE]
                self.assertNotIn(token, login.text)
                # The next handler obtains its own connection: the issuer must
                # commit before the browser can spend the session cookie.
                wallet = client.get(WALLET)
                self.assertEqual(wallet.status_code, 200)
                self.assertEqual(wallet.json(), {"account_id": str(account_id), "balance": 0})
                own_player = client.get(f"/api/v1/players/{account_id}/wallet")
                self.assertEqual(own_player.json(), wallet.json())
                self.assertEqual(
                    client.get(f"/api/v1/players/{other_player}/wallet").status_code, 404
                )
                roster = client.get("/api/v1/me/players")
                self.assertEqual(
                    (roster.status_code, roster.json()),
                    (200, {"player_ids": [str(account_id)], "next_after": None}),
                )
                history = client.get(HISTORY)
                self.assertEqual((history.status_code, history.json()), (200, {"bets": []}))
                for response in (wallet, own_player, roster, history):
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                    self.assertNotIn(token, response.text)
                self.assertEqual(
                    client.get(HISTORY + "?player_id=" + str(uuid.uuid4())).status_code, 400
                )
                with engine.connect() as connection:
                    session = connection.execute(
                        select(AccountSession.token_digest, AccountSession.revoked_at).where(
                            AccountSession.account_id == account_id
                        )
                    ).one()
                    self.assertEqual(session.token_digest, session_token_digest(token))
                    self.assertIsNone(session.revoked_at)
                denied = client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN})
                self.assertEqual(denied.status_code, 403)  # CSRF header is mandatory
                self.assertEqual(client.get(WALLET).status_code, 200)
                logout = client.post(
                    "/api/v1/auth/logout",
                    headers={"Origin": ORIGIN, CSRF_HEADER: csrf},
                )
                self.assertEqual(
                    (logout.status_code, logout.json()), (200, {"status": "signed_out"})
                )
                self.assertNotIn(SESSION_COOKIE, client.cookies)
                with engine.connect() as connection:
                    self.assertIsNotNone(
                        connection.scalar(
                            select(AccountSession.revoked_at).where(
                                AccountSession.account_id == account_id
                            )
                        )
                    )
                # A saved cookie, sent by a separate client after logout,
                # cannot read either resource even though the account remains.
                stale = TestClient(app, base_url=ORIGIN, client=("203.0.113.98", 50401))
                stale.cookies.set(SESSION_COOKIE, token, domain="game.example", path="/")
                self.assertEqual(stale.get(WALLET).status_code, 401)
                self.assertEqual(stale.get(HISTORY).status_code, 401)
                self.assertEqual(stale.get("/api/v1/me/players").status_code, 401)
                self.assertEqual(stale.get(f"/api/v1/players/{account_id}/wallet").status_code, 404)
                self.assertEqual(client.get(WALLET).status_code, 401)
                self.assertEqual(client.get(HISTORY).status_code, 401)
                # A fresh login is invalidated by account disablement, not just
                # an explicit logout or the browser forgetting its cookie.
                again = client.post(
                    "/api/v1/auth/login",
                    headers={"Origin": ORIGIN},
                    json={"role": "PLAYER", "identifier": name, "password": PASSWORD},
                )
                self.assertEqual(again.status_code, 200)
                with engine.begin() as connection:
                    connection.execute(
                        update(Account.__table__)
                        .where(Account.id == account_id)
                        .values(status="DISABLED", disabled_at=func.now())
                    )
                self.assertEqual(client.get(WALLET).status_code, 401)
                self.assertEqual(client.get(HISTORY).status_code, 401)
                self.assertEqual(client.get("/api/v1/me/players").status_code, 401)
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
