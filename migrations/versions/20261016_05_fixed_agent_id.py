"""Keep assigned Agent IDs fixed in V1; preserve initial NULL assignment.

Revision ID: 20261016_05
Revises: 20261016_04

No identifier reuse or anonymization policy is introduced by this revision.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261016_05"
down_revision: str | None = "20261016_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION protect_agent_id() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.login_kind = 'AGENT' AND OLD.login_identifier IS NOT NULL THEN
                    RAISE EXCEPTION 'Assigned agent identity cannot be deleted in V1'
                        USING ERRCODE = '23514';
                END IF;
                RETURN OLD;
            END IF;
            IF OLD.login_kind = 'AGENT' AND OLD.login_identifier IS NOT NULL
               AND (NEW.account_id IS DISTINCT FROM OLD.account_id
                    OR NEW.login_kind IS DISTINCT FROM OLD.login_kind
                    OR NEW.login_identifier IS DISTINCT FROM OLD.login_identifier) THEN
                RAISE EXCEPTION 'Agent ID cannot be changed after assignment'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_private_identities_fixed_agent_id
        BEFORE UPDATE OF account_id, login_kind, login_identifier OR DELETE ON private_identities
        FOR EACH ROW EXECUTE FUNCTION protect_agent_id()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_private_identities_fixed_agent_id ON private_identities")
    op.execute("DROP FUNCTION protect_agent_id()")
