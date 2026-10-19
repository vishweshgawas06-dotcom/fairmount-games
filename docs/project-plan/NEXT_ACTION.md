# Next Action

## Completed checkpoint — P03-T02h agent/player internal issuer

[P03-T02h](tasks/P03-T02h.md) adds role-bound, password-checked internal AGENT/PLAYER session issuance for already-activated fixed IDs, with D-03 deadlines, one-session replacement and success audit. Local non-DB suite/Ruff and [PostgreSQL CI 39208494711](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/39208494711) passed. There is **no public login** or provisioning/activation endpoint. Rate limits/failure audit, cookies/CSRF, resource/realtime authorization and approved recovery flows remain gates.

## Earlier checkpoint — P03-T02g account-change revocation

[P03-T02g](tasks/P03-T02g.md) adds transactional PostgreSQL backstops for D-03 session revocation on disablement, password-hash change and encrypted owner MFA factor replacement. Local non-DB tests/Ruff and [PostgreSQL CI 39208206922](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/39208206922) passed after fixing a superseded logout regression assertion. No public account mutation or login route exists. A future service still owes actor/scope/reason audit, MFA recovery-code rotation invalidation, rate limits, cookies/CSRF and realtime stale-session checks.

## Earlier checkpoint — P03-T02f internal logout

[P03-T02f](tasks/P03-T02f.md) implements token-presented session revocation and append-only, token-free audit. Local non-DB tests/Ruff and [PostgreSQL CI 39207809470](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/39207809470) passed. There is **no HTTP logout route**; cookie clearing/CSRF, proactive revocation on account changes, rate limits/failure audit and realtime invalidation remain gates.

## Earlier checkpoint — P03-T02e internal owner step-up

[P03-T02e](tasks/P03-T02e.md) adds a DB-time ten-minute MFA recency prerequisite and session-bound owner step-up with rollback-safe factor consumption. Local non-DB tests/Ruff and [PostgreSQL CI 39207020135](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/39207020135) passed. It exposes no route and does not grant an owner action. Next: rate limiting/failure audit, logout/revocation, secure cookies/CSRF and resource/realtime authorization.

## Earlier checkpoint — P03-T02d internal owner session issuance

[P03-T02d](tasks/P03-T02d.md) binds owner password + MFA verification to digest-only session issuance, invalidates the prior owner session after successful proof, and writes success audit atomically. Local non-DB tests/Ruff and [PostgreSQL CI 39205689122](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/39205689122) passed. **No public login exists.** Rate limits/failure audit, secure cookies/CSRF, authenticated owner step-up and API/realtime authorization still gate exposure.

## Earlier checkpoint — P03-T02c internal owner MFA proof

[P03-T02c](tasks/P03-T02c.md) adds transaction-scoped owner TOTP replay protection, single-use recovery-code consumption, and an append-only success event. Local non-DB tests/Ruff and [PostgreSQL CI 39205477305](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/39205477305) passed migration round-trip/metadata and rollback/replay tests. **It issues no session or access grant**. Next are bound password+MFA login, rate limits/failure accounting, secure cookies/CSRF and API/realtime authorization.

## Earlier checkpoint — P03-T02b internal session validation

[P03-T02b](tasks/P03-T02b.md) resolves a future trusted session token against locked account/session rows and PostgreSQL time; it slides idle expiry or revokes invalid state, without issuing tokens or exposing routes. Local non-DB tests/Ruff and [PostgreSQL CI 39204678377](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/39204678377) passed. Its returned data does not authorize a route. Next: secure issuance after mandatory owner MFA, rate limits, cookies/CSRF and realtime revocation.

## Earlier checkpoint — P03-T02a session schema

[P03-T02a](tasks/P03-T02a.md) adds a constrained PostgreSQL session table for the approved D-03 expiry policy, one unrevoked session per account, and owner MFA evidence; [the session boundary](auth/SESSION_SCHEMA_BOUNDARY.md) explicitly forbids interpreting this as login or authorization. Local non-DB tests/Ruff and [PostgreSQL CI 39204471202](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/39204471202) passed, including migration round-trip/metadata. Continue with token issuance and validation/revocation services, rate limiting and mandatory owner MFA before exposing login. This is not a production authentication system.

## Earlier checkpoint — P03-T01q local owner setup CLI

The owner granted permission to proceed through the plan in small tested/debugged steps and to ask when product/security decisions remain open. [P03-T01h](tasks/P03-T01h.md) adds a PostgreSQL pending/active credential-state table, structural checks, a one-way active-state guard, and DB tests. The [activation boundary](auth/ACTIVATION_STATE_DESIGN.md) states what the schema **cannot** guarantee. Local Ruff/non-DB tests and [CI run 38866772047](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38866772047) passed. There is no activation, account-creation, owner bootstrap, login, MFA or wallet endpoint.

**Next:** [P03-T01i](tasks/P03-T01i.md) security-event migration/tests passed [CI run 38867010258](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38867010258). The owner selected the [D-14 fixed `owner` login label](decisions/2026-10-16-owner-login-identifier.md). [P03-T01j](tasks/P03-T01j.md) pure TOTP/recovery-code helpers and tests passed [CI run 38867519974](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38867519974). The owner selected [D-15 deployment-owned out-of-database key custody](decisions/2026-10-16-owner-mfa-key-custody.md). [P03-T01k](tasks/P03-T01k.md) owner-bound AES-GCM TOTP encryption helper/tests passed [CI run 38867838880](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38867838880). The owner confirmed ten one-time recovery codes. [P03-T01l](tasks/P03-T01l.md) adds OWNER-only encrypted-factor/recovery-digest tables and DB tests; [CI run 38868491900](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38868491900) passed. [P03-T01m](tasks/P03-T01m.md) restricted versioned key-file loader and tests passed [CI run 39202950085](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/39202950085). [P03-T01n](tasks/P03-T01n.md) internal audited owner issue/reissue transactions and PostgreSQL tests passed [CI run 39203138653](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/39203138653). They neither commit nor display a secret. [P03-T01o](tasks/P03-T01o.md) internal expiry-checked owner activation transaction and PostgreSQL tests passed [CI run 39203336370](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/39203336370). [P03-T01p](tasks/P03-T01p.md) internal encrypted-factor enrollment/confirmation transaction and PostgreSQL tests passed [CI run 39203550214](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/39203550214). [P03-T01q](tasks/P03-T01q.md) terminal-only local development owner setup CLI and safety notes passed [CI run 39204219810](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/39204219810). [Storage boundary](auth/OWNER_MFA_STORAGE_BOUNDARY.md) still gates protected production setup, retry/recovery handling, rate limits, live login/session authorization and key backup/rotation. Never interpret an ENABLED account or a credential row as a logged-in owner/player.

## Completed checkpoints

- [P03-T01a](tasks/P03-T01a.md): owner-approved registration/identifier contract, no endpoints.
- [P03-T01b](tasks/P03-T01b.md): canonical ID helpers/constraints; [CI 38862897157](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38862897157).
- [P03-T01c](tasks/P03-T01c.md): login-kind/account-role binding; [CI 38863934464](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38863934464).
- [P03-T01d](tasks/P03-T01d.md) / [P03-T01e](tasks/P03-T01e.md): fixed V1 player usernames and Agent IDs; [CI 38864125620](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38864125620) / [CI 38865633220](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38865633220).
- [P03-T01f](tasks/P03-T01f.md) / [P03-T01g](tasks/P03-T01g.md): cryptographic primitives and permanent-password policy; [CI 38865947836](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38865947836) / [CI 38866281196](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38866281196).
- [D-12](decisions/2026-10-16-owner-bootstrap-and-agent-id-lifecycle.md): owner personally runs local setup; initial owner secret 24h with owner-only local pre-activation reissue; fixed Agent IDs. [D-13](decisions/2026-10-16-password-policy.md): 12–128 Unicode-character permanent passphrases.

Docker is unavailable here; real PostgreSQL evidence comes from GitHub CI. PR #1 remains open for owner review.

## Other open decisions

- **D-02 / D-11:** Retention, deletion/backups, username/Agent-ID reuse after anonymization.
- **D-03:** Manual owner recovery if both TOTP and all offline codes are lost; no self-service bypass.
- **POOL-01:** Funded reserve coverage/global bet acceptance rule; RNG remains independent.
- **D-06 / OPS-01 / D-04:** Round recovery, atomic settlement under load, measurable operational targets.

See [PROJECT_STATUS.md](PROJECT_STATUS.md) and the [delivery plan](DETAILED_DELIVERY_PLAN.md). Planning approval is not production-readiness evidence.
