# Next Action

## Completed checkpoint

**P02-T01 — Conceptual database schema and transaction design:** owner approved the [conceptual baseline](database/CONCEPTUAL_SCHEMA_AND_TRANSACTIONS.md) and [review findings](database/P02_T01_DESIGN_REVIEW.md) on 2026-10-16. The design task is complete. No SQL/ORM models, migrations, wallet, authentication or gameplay implementation exists. Approval does **not** settle the open decisions or authorize implementation.

## Proposed next small task — separate permission required

**P01-T03 — Reproducible local PostgreSQL test environment (foundation only).** Scope a Docker Compose PostgreSQL service with safe example credentials, database startup/teardown and an isolated test database; document clean setup commands and add an actual connection smoke test/CI service only if reviewable and verifiable. No domain tables, migrations, transfers, betting engine or real-money functionality. Use a supported Python 3.12/3.13 environment. Acceptance gate: documented clean-clone setup, tested database connection and teardown, and passing existing Python tests/lint on the supported environment. Ask the owner to approve this task before editing implementation/configuration files.

[P02-T01 task evidence](tasks/P02-T01.md) remains the record of what was and was not verified. The [delivery plan](DETAILED_DELIVERY_PLAN.md) keeps P01-T03 before schema migrations; a later P02-T02 physical-schema task needs its own scope and authorization.

## Unresolved decisions — do not guess

- **POOL-01:** Exact owner-funded reserve coverage formula, prior-round liabilities, replenishment/withdrawal controls and disclosure of any new global bet rejection. No outcome manipulation or failure to honor accepted winnings.
- **D-06 / OPS-01:** Round worker/cutoff/outcome persistence, settlement failure/retry and atomic global settlement at scale.
- **D-02 / PRIV-01:** Retention, deletion eligibility, backup behavior, mobile/username reuse and legal/privacy review.
- **D-03 / D-04:** Owner MFA recovery/session policy and measurable operational SLOs.

No phase or game code is production-verified. The catalogue fixture and API liveness tests do not validate the database or betting engine. [PROJECT_STATUS.md](PROJECT_STATUS.md) tracks the evidence and open gates.
