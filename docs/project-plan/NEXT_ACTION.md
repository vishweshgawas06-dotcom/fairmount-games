# Next Action

## Completed checkpoint — P03-T01b identifier constraints

The owner approved the [P03-T01a contract](auth/REGISTRATION_IDENTIFIER_CONTRACT.md) and separately authorized [P03-T01b](tasks/P03-T01b.md) on 2026-10-16: canonical player username/Agent-ID helpers, namespaced PostgreSQL validation/uniqueness migration and tests **only**. The migration and tests passed [CI run 38862897157](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38862897157): PostgreSQL upgrade/downgrade/metadata parity, constraint behavior, full suite and Ruff. Docker is unavailable locally. No registration, credentials, sessions or wallets were authorized.

**Next:** review the P03-T01b evidence; obtain fresh permission before any further implementation. Future provisioning must bind `login_kind` to `accounts.role`, enforce fixed usernames, resolve concurrent creation conflicts atomically and protect credentials. The database migration alone cannot register or authenticate an account.

## Completed checkpoints

[P03-T01a](tasks/P03-T01a.md) approved design; its contract covers fixed globally unique case-insensitive player usernames, generated Agent IDs, reserved names, shared/unverified mobile and single-use 24-hour initial credentials (not implemented). [P02-T02a](tasks/P02-T02a.md) account/identity/assignment schema passed [CI run 38859943741](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38859943741) on PostgreSQL 16.9; no login or wallet code exists. [P01-T03](tasks/P01-T03.md) local PostgreSQL foundation was verified in CI.

## Other open decisions

- **D-02 / D-11:** Retention, deletion/backups, username/Agent-ID reuse after anonymization.
- **D-03:** Manual owner recovery if both TOTP and all offline codes are lost; no self-service bypass.
- **POOL-01:** Funded reserve coverage/global bet acceptance rule; RNG remains independent.
- **D-06 / OPS-01 / D-04:** Round recovery, atomic settlement under load, measurable operational targets.

See [PROJECT_STATUS.md](PROJECT_STATUS.md) and the [delivery plan](DETAILED_DELIVERY_PLAN.md). Planning approval is not production-readiness evidence.
