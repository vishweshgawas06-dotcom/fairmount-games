# Next Action

## Active task — P03-T01a design review

The owner authorized [P03-T01a registration/identifier contract](tasks/P03-T01a.md) on 2026-10-16. The [design draft](auth/REGISTRATION_IDENTIFIER_CONTRACT.md) records the choices: globally unique case-insensitive player usernames of 3–32 ASCII characters starting with a letter; generated unique `AGT-` plus 10 unambiguous-character Agent IDs; reserved operator names/`agt-` player prefix; fixed player usernames; mobile saved as unverified non-unique contact data; a server-generated, single-use temporary credential shown once and expiring after 24 hours. Owner may create owner-managed or assigned players; agents create only their assigned players.

**Next:** owner reviews this combined contract and flags corrections. Do not mark the design task complete or implement registration, password/reset flows, sessions, DB uniqueness constraints or wallets without separately approved scoped tasks. The P02-T02a nullable/non-unique `login_identifier` schema remains unchanged. [D-11](decisions/2026-10-16-identifier-policy.md) records approved identifier choices but explicitly defers reuse after anonymization. [D-03](decisions/2026-10-16-owner-mfa-and-sessions.md) still lacks an approved manual all-factors-lost recovery process.

## Completed checkpoints

[P02-T02a](tasks/P02-T02a.md) account/identity/assignment schema passed [CI run 38859943741](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38859943741) on PostgreSQL 16.9; no login or wallet code exists. [P01-T03](tasks/P01-T03.md) local PostgreSQL foundation was verified in CI. Docker is unavailable in this sandbox.

## Other open decisions

- **D-02 / D-11:** Retention, deletion/backups, username/Agent-ID reuse after anonymization.
- **D-03:** Manual owner recovery if both TOTP and all offline codes are lost; no self-service bypass.
- **POOL-01:** Funded reserve coverage/global bet acceptance rule; RNG remains independent.
- **D-06 / OPS-01 / D-04:** Round recovery, atomic settlement under load, measurable operational targets.

See [PROJECT_STATUS.md](PROJECT_STATUS.md) and the [delivery plan](DETAILED_DELIVERY_PLAN.md). Planning approval is not production-readiness evidence.
