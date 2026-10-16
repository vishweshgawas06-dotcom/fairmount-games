# Next Action

## Completed checkpoint

**P02-T02a — First physical account-schema slice:** owner-approved and complete on 2026-10-16. [Task evidence](tasks/P02-T02a.md) records [passing CI run 38859943741](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38859943741) on Python 3.12 and PostgreSQL 16.9: isolated test DB, Alembic upgrade/downgrade/re-upgrade and metadata check, PostgreSQL constraint tests, existing tests, Ruff and Compose cleanup. Docker is absent in this sandbox; no local DB execution is claimed.

The API remains liveness-only. This schema is **not** account registration/login, authorization, wallet, betting or settlement. In particular, role-aware assignment checks, one-owner bootstrap/recovery, password hashing, username/mobile uniqueness and retention are not implemented.

## Next owner decision checkpoint — permission required

Before the next account/authentication implementation task, review **D-02 / PRIV-01** identifier and anonymization policy (username and mobile uniqueness/reuse after deletion), and **D-03** owner MFA recovery/session policy. We intentionally left `private_identities` login/mobile fields nullable and without uniqueness rather than guessing at these rules. A small decision task can document your choices without implementing code. Seek explicit permission before starting that review or a subsequent schema/auth task. Other P02-T02b migrations remain unapproved.

## Other unresolved decisions

- **POOL-01:** Funded game-reserve coverage and any disclosed global bet limit; never manipulate RNG or default on accepted wins.
- **D-06 / OPS-01:** Round worker, persisted outcome timing, failure/void sequencing and atomic settlement at scale.
- **D-02:** Exact retention, legal holds, deletion/backup behavior, beyond identity reuse.
- **D-04:** Measurable operational targets.

See [PROJECT_STATUS.md](PROJECT_STATUS.md) and the [delivery plan](DETAILED_DELIVERY_PLAN.md). A green API/catalogue/schema suite is not evidence of gameplay, wallet or production readiness.
