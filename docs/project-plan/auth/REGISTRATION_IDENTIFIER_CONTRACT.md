# P03-T01a — Registration and identifier contract (design only)

**Status:** Owner choices recorded 2026-10-16; proposal for a later scoped implementation review. No account-creation endpoint, login, uniqueness index, credential or session code is added by this task.

## Authority and identity

- V1 has one owner. Only the owner provisions agents. Agents may provision **players assigned to that agent only**; they cannot provision agents or owner-managed players. The owner may provision a player as owner-managed or assign the player to an existing agent. There is no public self-registration or agent sub-hierarchy.
- Account records have opaque internal IDs. A public Agent ID is a login identifier, **not** an authorization token. Current assignment and active account/session state—not knowledge of an Agent ID—determine who can manage a player.
- At account creation, the system validates that the actor is enabled and authorized for the selected role/assignment. New player balance starts at zero when wallets are introduced later; this task does not create wallets. Account creation, identity, assignment, one-time credential issuance and audit must be designed as one atomic operation; no partially provisioned active login should result from failure.
- Player name and mobile are required profile fields per locked requirements; agent registration records name/mobile details (agent contact number supports out-of-app communication). Mobile may be shared across accounts and is **unverified contact data** at registration. It cannot select an account or authorize a reset. Exact phone normalization, verification and contact/consent UX are future implementation-review items. Display names may use other scripts even though login IDs are ASCII.

## Player username contract (approved product rules)

- 3–32 ASCII characters, starts with a letter, remaining characters are letters, digits, underscore or hyphen: `^[A-Za-z][A-Za-z0-9_-]{2,31}$`. Store/compare a single canonical lowercase form for **global** case-insensitive uniqueness across all players, including different agents and owner-managed players. Collision at registration (including simultaneous requests) must reject without partial account/credential creation; the database must enforce uniqueness.
- Reserve `admin`, `owner`, `support`, `system`, `root` (case-insensitively) and the `agt-` prefix for platform/operator identifiers. Review the versioned reserved-name list and any brand/support lookalikes before making registration public. Do not silently assign a different username if the request conflicts.
- Player login username is **fixed in V1**; correcting a display name is a separate audited profile operation. A later owner-approved change to login names would need collision checks, session handling and audit. Reuse of an old username after eligible anonymization remains **undecided** (D-02/D-11); do not implement deletion/release/tombstone rules yet.

## Agent ID contract (approved product rules)

- Server generates `AGT-` followed by 10 cryptographically random uppercase characters from an unambiguous alphabet (`ABCDEFGHJKLMNPQRSTUVWXYZ23456789`). The ID is globally unique in its **agent** namespace and matched case-insensitively at login. On a rare collision, generate another candidate and rely on a database uniqueness constraint as the final guard. The ID is public-looking and **not secret**; knowledge of it alone grants no access.
- Exact Agent-ID reuse after eligible anonymization/agent removal is not approved. Never overwrite an agent's historical attribution or reuse an internal account UUID for a different person.

## One-time activation credential (approved direction)

- At agent/player provisioning, the server creates a high-entropy **single-use temporary credential**; the authorized owner/agent creator can see it **once** in a protected dashboard. The authorized creator provides the Agent ID or player username plus the temporary credential via an appropriate secure out-of-band method. Do not keep readable copies in a database, logs, analytics or ordinary WhatsApp chat; there is no WhatsApp integration in V1.
- The temporary credential expires after **24 hours** if unused. The first successful activation invalidates it atomically and requires the agent/player to choose their own password; store only an appropriately configured Argon2id hash of that password. An expired/used credential cannot be extended or replayed. Never allow login with a provisional credential as a fully activated long-lived session.
- Owner may initiate agent/player password reset using a **new** one-time process with audit, reason, rate limiting and full affected-session revocation under D-03. Agent permission to reset an assigned player's password has **not** been approved; do not add it by assumption. Reset delivery/identity verification, first-login timing, failed-attempt limits and CSRF/session details require their own scoped security review before code.

## API/transaction shape for later tasks — not implemented

- Future registration inputs: requested player username, display name, mobile number and (for owner) selected agent or owner-managed scope. Agent ID is generated, not submitted by the client. Browser/client state cannot forge creator role, assignment or a point balance.
- Proposed transaction: authenticate/authorize creator → validate normal form, required profile fields and reserved names → create account/private identity/assignment (if any) → persist one-time credential verifier plus audit → commit; return only permitted public ID and one-time activation material. Unique-key conflicts and all failures roll back the entire operation. The exact API paths/schemas, rate limits, audit retention, credential distribution and database layout are **not yet approved**.
- Registration, activation, password reset, login and session issuance are different operations. Account provisioning alone is not evidence of authentication or authorization. Test creator scopes, disabled accounts, duplicates with different case, concurrent collisions, fixed usernames, owner-managed players, shared mobiles, expired/replayed activation and credential leaks.

## Open dependencies and implementation gate

- D-02/D-11: username and Agent-ID reuse after anonymization/deletion, precise retention and backup policy, data minimization. No deletion job may be built yet.
- D-03: TOTP and one-active-session baseline is approved; manual all-factors-lost owner recovery is not. Details of protected credential delivery, owner step-up, login/reset abuse controls and password lifecycle need separate threat review.
- The P02-T02a `private_identities.login_identifier` field is currently nullable and **not** unique. A later scoped migration should introduce role/namespace-aware canonical identifiers and database-backed uniqueness with migration/collision tests; it must not reinterpret this contract as permission to implement login or wallets.

**P03-T01a gate:** owner-specified identifier/activation decisions are documented and reviewable. Marking this *design task* complete does not approve the future migration or authentication code; each receives a separate small task and PostgreSQL/security test plan.
