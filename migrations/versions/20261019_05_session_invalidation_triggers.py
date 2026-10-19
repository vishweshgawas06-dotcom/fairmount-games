"""Revoke affected sessions on account disable, password and owner MFA changes.

Revision ID: 20261019_05
Revises: 20261019_04

These triggers are a DB backstop, not authorization for the underlying change.
Caller-provided actor/reason/audit and prompt WebSocket revalidation are separate.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261019_05"
down_revision: str | None = "20261019_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION revoke_sessions_on_account_disable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.status IS DISTINCT FROM NEW.status AND NEW.status = 'DISABLED' THEN
                UPDATE account_sessions
                   SET revoked_at = GREATEST(clock_timestamp(), issued_at)
                 WHERE account_id = NEW.id AND revoked_at IS NULL;
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_sessions_account_disabled
        AFTER UPDATE OF status ON accounts
        FOR EACH ROW EXECUTE FUNCTION revoke_sessions_on_account_disable()
    """)
    op.execute("""
        CREATE FUNCTION revoke_sessions_on_password_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.password_hash IS DISTINCT FROM NEW.password_hash THEN
                UPDATE account_sessions
                   SET revoked_at = GREATEST(clock_timestamp(), issued_at)
                 WHERE account_id = NEW.account_id AND revoked_at IS NULL;
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_sessions_password_changed
        AFTER UPDATE OF password_hash ON account_credentials
        FOR EACH ROW EXECUTE FUNCTION revoke_sessions_on_password_change()
    """)
    op.execute("""
        CREATE FUNCTION revoke_sessions_on_owner_mfa_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.key_version IS DISTINCT FROM NEW.key_version
               OR OLD.nonce IS DISTINCT FROM NEW.nonce
               OR OLD.ciphertext IS DISTINCT FROM NEW.ciphertext
               OR OLD.confirmed_at IS DISTINCT FROM NEW.confirmed_at THEN
                UPDATE account_sessions
                   SET revoked_at = GREATEST(clock_timestamp(), issued_at)
                 WHERE account_id = NEW.account_id AND revoked_at IS NULL;
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_sessions_owner_mfa_changed
        AFTER UPDATE OF key_version, nonce, ciphertext, confirmed_at ON owner_mfa
        FOR EACH ROW EXECUTE FUNCTION revoke_sessions_on_owner_mfa_change()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_sessions_owner_mfa_changed ON owner_mfa")
    op.execute("DROP FUNCTION revoke_sessions_on_owner_mfa_change()")
    op.execute("DROP TRIGGER trg_sessions_password_changed ON account_credentials")
    op.execute("DROP FUNCTION revoke_sessions_on_password_change()")
    op.execute("DROP TRIGGER trg_sessions_account_disabled ON accounts")
    op.execute("DROP FUNCTION revoke_sessions_on_account_disable()")
