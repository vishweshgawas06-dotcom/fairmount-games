# Next Action

## Completed checkpoint — P03-T01p internal owner MFA enrollment

The owner granted permission to proceed through the plan in small tested/debugged steps and to ask when product/security decisions remain open. [P03-T01h](tasks/P03-T01h.md) adds a PostgreSQL pending/active credential-state table, structural checks, a one-way active-state guard, and DB tests. The [activation boundary](auth/ACTIVATION_STATE_DESIGN.md) states what the schema **cannot** guarantee. Local Ruff/non-DB tests and [CI run 38866772047](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38866772047) passed. There is no activation, account-creation, owner bootstrap, login, MFA or wallet endpoint.

**Next:** [P03-T01i](tasks/P03-T01i.md) security-event migration/tests passed [CI run 38867010258](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38867010258). The owner selected the [D-14 fixed `owner` login label](decisions/2026-10-16-owner-login-identifier.md). [P03-T01j](tasks/P03-T01j.md) pure TOTP/recovery-code helpers and tests passed [CI run 38867519974](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38867519974). The owner selected [D-15 deployment-owned out-of-database key custody](decisions/2026-10-16-owner-mfa-key-custody.md). [P03-T01k](tasks/P03-T01k.md) owner-bound AES-GCM TOTP encryption helper/tests passed [CI run 38867838880](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38867838880). The owner confirmed ten one-time recovery codes. [P03-T01l](tasks/P03-T01l.md) adds OWNER-only encrypted-factor/recovery-digest tables and DB tests; [CI run 38868491900](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38868491900) passed. [P03-T01m](tasks/P03-T01m.md) restricted versioned key-file loader and tests passed [CI run 39202950085](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/39202950085). [P03-T01n](tasks/P03-T01n.md) internal audited owner issue/reissue transactions and PostgreSQL tests passed [CI run 39203138653](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/39203138653). They neither commit nor display a secret. [P03-T01o](tasks/P03-T01o.md) internal expiry-checked owner activation transaction and PostgreSQL tests passed [CI run 39203336370](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/39203336370). [P03-T01p](tasks/P03-T01p.md) internal encrypted-factor enrollment/confirmation transaction and PostgreSQL tests passed [CI run 39203550214](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/39203550214). [Storage boundary](auth/OWNER_MFA_STORAGE_BOUNDARY.md) still gates a protected local CLI/UI, rate limits, live login/session authorization and key backup/rotation. Never interpret an ENABLED account or a credential row as a logged-in owner/player.

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
