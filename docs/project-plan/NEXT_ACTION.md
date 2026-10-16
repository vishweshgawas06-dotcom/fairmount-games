# Next Action

## Completed checkpoint

**P01-T03 — Local PostgreSQL test environment:** owner-approved, completed on 2026-10-16. [Task evidence](tasks/P01-T03.md) records a localhost-only Compose service, isolated test database check and [passing GitHub CI run 38859064842](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38859064842): checkout/install, Compose up, test connection, existing unit tests, Ruff and Compose down/volume removal all passed. Docker is not installed in this sandbox, so local Docker execution remains unverified here. No application schema or gameplay code exists.

P02-T01 [conceptual design](database/CONCEPTUAL_SCHEMA_AND_TRANSACTIONS.md) was approved as a planning baseline on 2026-10-16; that does not approve physical schema details or unresolved product decisions.

## Active task — P02-T02a

Owner authorized the [first account/identity/assignment schema slice](tasks/P02-T02a.md) on 2026-10-16. SQLAlchemy models and one Alembic migration are prepared with PostgreSQL-only tests. **Next:** observe clean GitHub CI migration upgrade/downgrade/re-upgrade, metadata check, constraint tests, existing tests/lint and teardown; fix failures and record actual evidence before completion. No authentication flow, wallets, transfers, roulette, settlement or destructive privacy cleanup are included. Docker is absent in this sandbox, so local PostgreSQL tests cannot be claimed.

The [delivery plan](DETAILED_DELIVERY_PLAN.md) requires phase-specific evidence. `P01-T02` frontend workspace remains deferred until client work is scoped.

## Unresolved decisions — do not guess

- **POOL-01:** Exact owner-funded reserve coverage formula, prior-round liabilities, replenishment/withdrawal controls and disclosure of any new global bet rejection. No outcome manipulation or failure to honor accepted winnings.
- **D-06 / OPS-01:** Round worker/cutoff/outcome persistence, settlement failure/retry and atomic global settlement at scale.
- **D-02 / PRIV-01:** Retention, deletion eligibility, backup behavior, mobile/username reuse and legal/privacy review.
- **D-03 / D-04:** Owner MFA recovery/session policy and measurable operational SLOs.

The catalogue fixture, API liveness and PostgreSQL connection check do not validate a database schema or betting engine. [PROJECT_STATUS.md](PROJECT_STATUS.md) tracks the evidence and remaining gates.
