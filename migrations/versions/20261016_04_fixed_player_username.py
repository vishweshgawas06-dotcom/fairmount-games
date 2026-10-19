"""Prevent reassignment or clearing of an already assigned player login name.

Revision ID: 20261016_04
Revises: 20261016_03

This deliberately does not define a deletion/anonymization or username reuse policy.
An initial NULL -> player login assignment remains possible; once assigned, the
username is fixed in V1. PostgreSQL trigger behavior is tested separately because
Alembic autogenerate does not compare database triggers.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261016_04"
down_revision: str | None = "20261016_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION protect_player_username() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.login_kind = 'PLAYER' AND OLD.login_identifier IS NOT NULL THEN
                    RAISE EXCEPTION 'Assigned player identity cannot be deleted in V1'
                        USING ERRCODE = '23514';
                END IF;
                RETURN OLD;
            END IF;
            IF OLD.login_kind = 'PLAYER' AND OLD.login_identifier IS NOT NULL
               AND (NEW.account_id IS DISTINCT FROM OLD.account_id
                    OR NEW.login_kind IS DISTINCT FROM OLD.login_kind
                    OR NEW.login_identifier IS DISTINCT FROM OLD.login_identifier) THEN
                RAISE EXCEPTION 'Player login username cannot be changed after assignment'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_private_identities_fixed_player_username
        BEFORE UPDATE OF account_id, login_kind, login_identifier OR DELETE ON private_identities
        FOR EACH ROW EXECUTE FUNCTION protect_player_username()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_private_identities_fixed_player_username ON private_identities")
    op.execute("DROP FUNCTION protect_player_username()")
