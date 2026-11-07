"""Member activation failure surface and pending-secret reissue audit type."""

from alembic import op

revision = "20261107_01"
down_revision = "20261103_03"
branch_labels = None
depends_on = None

_OLD_EVENTS = """
    event_type IN (
        'OWNER_BOOTSTRAP_ISSUED', 'OWNER_BOOTSTRAP_REISSUED',
        'INITIAL_CREDENTIAL_ISSUED', 'INITIAL_CREDENTIAL_CONSUMED',
        'PASSWORD_CHANGED', 'OWNER_MFA_ENROLLED', 'OWNER_MFA_VERIFIED',
        'OWNER_SESSION_STARTED', 'SESSION_REVOKED', 'MEMBER_SESSION_STARTED',
        'ACCOUNT_ENABLED', 'ACCOUNT_DISABLED',
        'AGENT_ASSIGNED', 'AGENT_UNASSIGNED'
    ) AND source IN ('LOCAL_CLI', 'DASHBOARD', 'SELF_SERVICE')
    AND (actor_account_id IS NOT NULL OR
         (source = 'LOCAL_CLI' AND event_type IN
          ('OWNER_BOOTSTRAP_ISSUED', 'OWNER_BOOTSTRAP_REISSUED')))
"""

_NEW_EVENTS = """
    event_type IN (
        'OWNER_BOOTSTRAP_ISSUED', 'OWNER_BOOTSTRAP_REISSUED',
        'INITIAL_CREDENTIAL_ISSUED', 'INITIAL_CREDENTIAL_CONSUMED',
        'PASSWORD_CHANGED', 'OWNER_MFA_ENROLLED', 'OWNER_MFA_VERIFIED',
        'OWNER_SESSION_STARTED', 'SESSION_REVOKED', 'MEMBER_SESSION_STARTED',
        'ACCOUNT_ENABLED', 'ACCOUNT_DISABLED',
        'AGENT_ASSIGNED', 'AGENT_UNASSIGNED', 'INITIAL_CREDENTIAL_REISSUED'
    ) AND source IN ('LOCAL_CLI', 'DASHBOARD', 'SELF_SERVICE')
    AND (actor_account_id IS NOT NULL OR
         (source = 'LOCAL_CLI' AND event_type IN
          ('OWNER_BOOTSTRAP_ISSUED', 'OWNER_BOOTSTRAP_REISSUED')))
"""

_OLD_FAILURES = """subject_digest COLLATE "C" ~ '^[0-9a-f]{64}$'
    AND source_digest COLLATE "C" ~ '^[0-9a-f]{64}$'
    AND surface IN ('OWNER_LOGIN','MEMBER_LOGIN','OWNER_MFA')
    AND outcome IN ('FAILED','THROTTLED')"""

_NEW_FAILURES = """subject_digest COLLATE "C" ~ '^[0-9a-f]{64}$'
    AND source_digest COLLATE "C" ~ '^[0-9a-f]{64}$'
    AND surface IN ('OWNER_LOGIN','MEMBER_LOGIN','OWNER_MFA','MEMBER_ACTIVATION')
    AND outcome IN ('FAILED','THROTTLED')"""


def _replace(events, failures):
    op.drop_constraint("ck_security_events_valid", "security_events", type_="check")
    op.create_check_constraint("ck_security_events_valid", "security_events", events)
    op.drop_constraint("ck_auth_failure_events_shape", "auth_failure_events", type_="check")
    op.create_check_constraint("ck_auth_failure_events_shape", "auth_failure_events", failures)


def upgrade():
    _replace(_NEW_EVENTS, _NEW_FAILURES)


def downgrade():
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM security_events
                       WHERE event_type = 'INITIAL_CREDENTIAL_REISSUED')
               OR EXISTS (SELECT 1 FROM auth_failure_events
                          WHERE surface = 'MEMBER_ACTIVATION') THEN
                RAISE EXCEPTION 'refusing to discard member activation audit support';
            END IF;
        END $$;
    """)
    _replace(_OLD_EVENTS, _OLD_FAILURES)
