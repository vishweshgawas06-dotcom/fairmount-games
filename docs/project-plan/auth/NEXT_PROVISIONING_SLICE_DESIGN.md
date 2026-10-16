# P03-T01c — Role binding and provisioning design proposal

**Status:** Role-binding design implemented under the owner’s subsequent broad step-by-step implementation permission (2026-10-16); PostgreSQL CI evidence pending. The later provisioning/security sections remain proposals, not accepted product/security choices. This proposal follows the approved [registration/identifier contract](REGISTRATION_IDENTIFIER_CONTRACT.md) and the completed [identifier constraint slice](../tasks/P03-T01b.md).

## Why a further slice is needed

P03-T01b restricts a `private_identities` row to a canonical namespaced player username or Agent ID (or neither), and rejects duplicates in that namespace. It does **not** prevent a `PLAYER` login kind on an `AGENT` account, mutable login IDs, or direct inserts without registration audit/credentials. No registration, activation or login route exists. The next useful small implementation slice could bind non-null login kind to account role **without** pretending to provision users.

## P03-T01c — database role binding slice

- Keep the existing required FK from `private_identities.account_id` to `accounts.id` so identities with **both** login fields null still require a real account. Add a PostgreSQL unique key on `accounts(id, role)` and a composite FK from `(private_identities.account_id, private_identities.login_kind)` to `(accounts.id, accounts.role)`. The FK's default `MATCH SIMPLE` permits a null `login_kind`; P03-T01b's CHECK requires null kind and identifier together. A **non-null** kind must match the parent role. An owner can retain an identity row with both login fields null; this does not specify owner login credentials.
- The migration is designed to fail safely if pre-existing non-null login kinds disagree with account roles; never silently recast an Agent ID as a username or discard identity data. Before production deployment, inventory legacy rows and write a separate approved backfill plan if needed. Downgrade removes only the new FK/unique key; it would not rewrite identities.
- No endpoints or password/activation code are added in this slice. Do not claim this FK enforces username immutability: updates from one valid player username to another remain possible until a separately reviewed guard is implemented. Account role changes for accounts with no login kind also remain possible at this stage; role-change policy is a future gate.

### PostgreSQL acceptance matrix for P03-T01c

| Scenario | Expected |
| --- | --- |
| Agent ID on AGENT and username on PLAYER | Accepted; duplicate/canonical rules still enforced by P03-T01b |
| PLAYER kind on AGENT; AGENT kind on PLAYER; either kind on OWNER | Rejected by FK; proposed provisioning transaction must roll back entirely |
| OWNER/PLAYER/AGENT identity with both login fields null | Allowed, retaining existing account FK |
| Change account role under a bound non-null identity | Rejected, not silently detached; document role-change policy separately |
| Insert/update identity with missing account, invalid format, mixed-case ID, duplicate ID | Rejected by existing FK/CHECK/unique index |
| Upgrade/downgrade/re-upgrade and Alembic metadata comparison | Pass on clean test DB; legacy role mismatch fails without data modification |

Integration tests must execute against PostgreSQL, use transactional rollback, and exercise insert **and update** paths plus the CHECK/FK null interaction. P03-T01b tests use matching account roles for valid identifiers; P03-T01c tests isolate mismatched pairs and an explicit migration-failure check. No SQLite proxy is adequate. CI should run Python tests/Ruff plus migration round-trip and `alembic check` before completion.

## Later provisioning and auth slices (not implemented here)

1. **Security/transaction specification:** design authenticated creator authority (owner creates agents/owner-managed or assigned players; agent creates only currently assigned players), disabled-actor and disabled-target behavior, owner MFA step-up, CSRF/rate limits, audit schema and redaction, protected once-only activation delivery, and retry/idempotency semantics. D-03 session/MFA baseline is approved, but no auth foundation exists yet. API paths, exact request/response errors, credential-delivery UX, abuse limits, audit retention and bootstrap owner flow need explicit review. Mobile stays unverified and non-unique, never password-reset authority alone.
2. **Registration implementation only after prerequisites:** one PostgreSQL transaction for account, private identity, current assignment where appropriate, credential verifier and audit; authorize from server-side session/role/assignment, never client-supplied actor/agent scope. Normalize requested username, generate Agent ID with a cryptographic generator, and treat the unique index as the final collision guard. Player conflict fails as a whole; generated Agent-ID collision may retry **the entire safe transaction** with a new ID and bounded attempts. Distinguish unique conflicts from unrelated integrity failures; no partial account or leaked activation credential. Plan a decision about when an account becomes usable: no incomplete active login when credential/audit issuance fails.
3. **Activation and login/security separately:** single-use, 24-hour temporary credential shown once to authorized creator, hashed verifier and atomic consumption/forced Argon2id password setup; owner-initiated resets and session revocation; D-03 TOTP, recovery codes, role-specific session expiries and sensitive-action step-up. Concurrent requests, replay/expiry, logging/secret exposure, owner-managed-player visibility and assignment changes all need negative tests. There is no public self-registration or agent-created sub-agent.
4. **Fixed names and data lifecycle:** propose a database/service immutability guard for player login IDs after initial assignment, with a documented exception only for a separately approved future migration. Decide whether owner/agent identifiers can change, and how D-02 deletion, retention and identity reuse will be handled **before** implementing release or anonymization workflows. A role-binding FK alone cannot make identifiers immutable.

## Review questions before code

- Is P03-T01c's composite-FK approach and migration-fails-on-mismatch policy acceptable as a **separate DB-only slice**, with nullable login fields kept for existing identities? This design has been implemented in the bounded DB-only slice under the owner’s later broad permission.
- Should a later strict database guard prevent *all* updates to non-null player usernames (including administrator SQL), while allowing initial null → username assignment? The V1 product rule is already fixed usernames, but this technical mechanism needs review.
- Which task should specify the owner bootstrap, credential delivery, rate limits and audit retention before account-provisioning APIs? These are not answered here.

**Boundary:** no wallet/issuance, game reserve, RNG, betting logic, registration route or authentication code in this design stage.
