# P03-T01h — Credential-state schema and activation boundary

**Status:** Database-only schema completed 2026-10-16; [CI run 38866772047](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38866772047) passed. No activation/registration/owner setup endpoint exists.

## Storage states

One `account_credentials` row per account, with the original account FK retained. The database allows only:

| State | Stored values | Access implication |
| --- | --- | --- |
| Pending | SHA-256 digest of a 256-bit generated initial secret, issued timestamp, expiry exactly 24 hours later; no password hash or consumption timestamp | **No login or management access.** A future service must check current database time and possession; an expired row is still pending data, not usable. |
| Activated password | Argon2id hash and changed/consumed timestamps; initial digest and expiry cleared | Password is set, but account status/session/role authorization still required. **Owner management also requires completed MFA enrollment and step-up.** |

The DB CHECK guards null combinations, digest shape and the 24-hour issuance interval, **not** real-time expiry, possession, Argon2id parameter validity or authorization. A trigger blocks an activated row from returning to pending or being deleted, while pending reissue can replace the old digest and timestamps in one update. The active password may be replaced in a later authorized reset with audit and session revocation; no reset service exists yet. Do not expose direct DB access as a credential workflow.

## Later service transaction gates — not implemented here

- **Owner bootstrap:** the owner personally runs an owner-only local deployment command. In a PostgreSQL transaction, verify no prior owner and create the single OWNER row, pending verifier and minimal audit. Commit before showing the one-time initial secret. A failure to deliver/read output cannot create a second owner; an owner-only deployment-shell *pre-activation* local reissue path rotates the pending digest, expires it in 24 hours and records audit. Never reset an activated owner's MFA through bootstrap. Owner MFA enrollment and recovery-code display must occur before management access; D-03 prohibits all-factors-lost self-service bypass.
- **Agent/player provisioning:** only authenticated authorized creators, enabled accounts, current assignments, audit and credential issuance in one transaction. Return initial secret once to a protected creator dashboard after commit; no plaintext persistence, email/WhatsApp integration or logs. Unique conflicts roll back all related account/assignment/credential/audit work. Creator scope and response-loss/reissue policy still require security review.
- **Activation:** P03-T01o now provides an internal OWNER-only transaction (not an exposed route): take a row lock on a pending credential; compare the supplied secret digest in constant time; compare `expires_at` to a database time in that transaction; validate/hash a 12–128-character permanent passphrase; clear digest/expiry, set consumed/password timestamps and audit, then commit. Competing uses must result in one success at most. Authentication/login, MFA and session creation are later steps; a temporary secret is not a reusable session. Do not offer ambiguous account-enumerating error messages. Introduce request-size/rate limits and CSRF protection where relevant before any route goes live.

## Security and migration cautions

- `accounts.status = ENABLED` is not evidence of activation; future access gates must check credential state, status, owner MFA and valid session. The initial private identity may be null before provisioning, but login must not be possible without the approved identifier binding and verified credential state.
- Pending credentials can expire without violating the DB CHECK; do not use a wall-clock `now()` CHECK. The issued/expiry timestamps cannot by themselves prove secret possession; the SQL structure does not restrict a privileged direct writer from setting an active row. DB roles, service authorization, and audit need review.
- D-02 retention/backups, historic credential-audit retention, reset policy and Agent ID/username reuse after anonymization remain open. No cleanup/deletion/tombstone process is introduced. Hard deletion of an activated credential is blocked until an approved lifecycle migration.
- CI must run clean upgrade/downgrade/re-upgrade, Alembic metadata parity and PostgreSQL pending/active/reissue/invalid-shape/replay-regression tests. This task does not imply production auth readiness.
