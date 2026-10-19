"""PostgreSQL D-03 session invalidation on account/credential/MFA mutation."""

import os
import secrets
import unittest
from types import MappingProxyType

from fairmount_api.db.models import Account, AccountCredential, AccountSession, OwnerMFA
from fairmount_api.identity.credentials import hash_password
from fairmount_api.identity.mfa import generate_totp_secret, totp_code
from fairmount_api.identity.mfa_encryption import encrypt_totp_secret
from fairmount_api.identity.mfa_keys import MFAKeyring
from fairmount_api.identity.owner_activation import activate_initial_owner
from fairmount_api.identity.owner_bootstrap import bootstrap_owner
from fairmount_api.identity.owner_login import issue_owner_session
from fairmount_api.identity.owner_mfa_enrollment import (
    begin_owner_mfa_enrollment,
    confirm_owner_mfa_enrollment,
)
from fairmount_api.identity.session_validation import resolve_session
from sqlalchemy import create_engine, func, select, update

from infrastructure.local_db_url import local_database_url

PASSWORD = "a strong private owner passphrase"


@unittest.skipUnless(
    os.environ.get("FAIRMOUNT_RUN_DB_TESTS") == "1", "PostgreSQL test DB not set up"
)
class SessionInvalidationTriggerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_engine(local_database_url(test=True))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        self.keyring = MFAKeyring(1, MappingProxyType({1: secrets.token_bytes(32)}))
        pending_owner = bootstrap_owner(self.connection)
        self.owner_id = activate_initial_owner(self.connection, pending_owner.secret, PASSWORD)
        pending_factor = begin_owner_mfa_enrollment(self.connection, self.keyring)
        now = self.connection.scalar(select(func.clock_timestamp()))
        confirmed = confirm_owner_mfa_enrollment(
            self.connection, totp_code(pending_factor.secret, int(now.timestamp())), self.keyring
        )
        self.issued = issue_owner_session(
            self.connection,
            "owner",
            PASSWORD,
            "recovery",
            confirmed.recovery_codes[0],
            self.keyring,
        )

    def tearDown(self) -> None:
        self.transaction.rollback()
        self.connection.close()

    def revoked_at(self):
        return self.connection.scalar(
            select(AccountSession.revoked_at).where(AccountSession.id == self.issued.session_id)
        )

    def test_disable_revokes_in_same_transaction_and_rollback_restores(self) -> None:
        with self.assertRaises(RuntimeError), self.connection.begin_nested():
            self.connection.execute(
                update(Account.__table__)
                .where(Account.id == self.owner_id)
                .values(status="DISABLED")
            )
            self.assertIsNotNone(self.revoked_at())
            raise RuntimeError("Simulated failure before disablement commit")
        self.assertIsNone(self.revoked_at())
        self.assertIsNotNone(resolve_session(self.connection, self.issued.token))
        self.connection.execute(
            update(Account.__table__).where(Account.id == self.owner_id).values(status="DISABLED")
        )
        self.assertIsNotNone(self.revoked_at())
        self.assertIsNone(resolve_session(self.connection, self.issued.token))

    def test_password_change_revokes_but_non_password_edit_does_not(self) -> None:
        self.connection.execute(
            update(AccountCredential.__table__)
            .where(AccountCredential.account_id == self.owner_id)
            .values(password_changed_at=func.clock_timestamp())
        )
        self.assertIsNone(self.revoked_at())
        self.connection.execute(
            update(AccountCredential.__table__)
            .where(AccountCredential.account_id == self.owner_id)
            .values(
                password_hash=hash_password("another strong private owner passphrase"),
                password_changed_at=func.clock_timestamp(),
            )
        )
        self.assertIsNotNone(self.revoked_at())
        self.assertIsNone(resolve_session(self.connection, self.issued.token))

    def test_factor_replacement_revokes_but_totp_step_update_does_not(self) -> None:
        current_step = self.connection.scalar(select(OwnerMFA.last_accepted_step))
        self.connection.execute(
            update(OwnerMFA.__table__)
            .where(OwnerMFA.account_id == self.owner_id)
            .values(last_accepted_step=current_step + 1)
        )
        self.assertIsNone(self.revoked_at())
        version, key = self.keyring.active_key()
        replacement = encrypt_totp_secret(
            generate_totp_secret(), account_id=self.owner_id, key=key, key_version=version
        )
        self.connection.execute(
            update(OwnerMFA.__table__)
            .where(OwnerMFA.account_id == self.owner_id)
            .values(nonce=replacement.nonce, ciphertext=replacement.ciphertext)
        )
        self.assertIsNotNone(self.revoked_at())
        self.assertIsNone(resolve_session(self.connection, self.issued.token))


if __name__ == "__main__":
    unittest.main()
