# Next Action

## Completed checkpoint — P03-T01e fixed Agent IDs

The owner superseded the earlier design-only restriction with permission to advance through the phases **in small tested and debugged steps**, asking for decisions where needed. [P03-T01c](tasks/P03-T01c.md) adds a PostgreSQL composite FK binding non-null login kind to account role, with migration rollback and insert/update/null-path tests. Local Ruff/non-DB tests and [CI run 38863934464](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38863934464) passed, including PostgreSQL legacy mismatch rollback and FK checks. No registration, credential, session or wallet behavior is added by this slice. P03-T01d enforces fixed player usernames only; [CI run 38864125620](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38864125620) passed.

**Next:** [D-12](decisions/2026-10-16-owner-bootstrap-and-agent-id-lifecycle.md) approved trusted local owner setup and fixed V1 Agent IDs. [P03-T01e](tasks/P03-T01e.md) Agent-ID immutability trigger and tests passed [CI run 38865633220](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38865633220). Next: design the credential/MFA foundations for the approved owner bootstrap and registration flows, clarifying unresolved secret expiry/reissue and secure handoff rules before implementing them. Plan owner bootstrap/activation only with credential and MFA security foundations. [Provisioning design](auth/NEXT_PROVISIONING_SLICE_DESIGN.md) identifies remaining gates including fixed-name enforcement, account creation/activation atomicity, audit, bootstrap and authorization.

## Completed checkpoints

[P03-T01a](tasks/P03-T01a.md) approved contract: fixed globally unique case-insensitive player usernames, generated Agent IDs, reserved names, shared/unverified mobile and single-use 24-hour initial credentials (not implemented). [P03-T01b](tasks/P03-T01b.md) canonical ID helpers/DB constraints passed [CI run 38862897157](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38862897157). [P02-T02a](tasks/P02-T02a.md) account/identity/assignment schema passed [CI run 38859943741](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38859943741) on PostgreSQL 16.9. Docker is unavailable locally; no login or wallet code exists.

## Other open decisions

- **D-02 / D-11:** Retention, deletion/backups, username/Agent-ID reuse after anonymization.
- **D-03:** Manual owner recovery if both TOTP and all offline codes are lost; no self-service bypass.
- **POOL-01:** Funded reserve coverage/global bet acceptance rule; RNG remains independent.
- **D-06 / OPS-01 / D-04:** Round recovery, atomic settlement under load, measurable operational targets.

See [PROJECT_STATUS.md](PROJECT_STATUS.md) and the [delivery plan](DETAILED_DELIVERY_PLAN.md). Planning approval is not production-readiness evidence.
