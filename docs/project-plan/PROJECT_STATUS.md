# Project Status

**Current phase:** P02 conceptual design baseline approved; database implementation not started

**Current task:** P01-T03 owner-authorized local PostgreSQL foundation; Compose/connection verification pending CI

**Implementation status:** Initial FastAPI liveness foundation only; no schema, wallet or betting engine

**Specification status:** Payout/settlement and legal-position catalogue approved; POOL-01/D-06/D-02 details remain open

**Verification status:** P01-T01/API CI and P02-T01 conceptual review complete. P01-T03 local PostgreSQL Compose startup and connection check await GitHub CI; Docker is unavailable in this sandbox.

**Last updated:** 2026-10-16

## Delivery plan (owner-approved sequence)

- [Detailed delivery plan](DETAILED_DELIVERY_PLAN.md) prepared and owner-approved on 2026-10-15 with small task outlines, dependencies, owner decision checkpoints, and test/review gates for P00–P19. Individual implementation tasks still require separate permission; open decisions remain open.
- Owner reconfirmed the goal of a realistic-feeling European roulette machine with a smoothly spinning wheel and ball. Visual specifics and device budgets remain design review checkpoints; the animation must follow the authoritative server result.
- The owner reaffirmed the independent server-side RNG rule and requested readable code, appropriate error handling, standard accessible UI/UX, staged testing/debugging, permission checkpoints, Markdown status updates, and GitHub commit/push at completed stages. These are reflected in the workflow rules.
- After separate permission for P01-T01 verification, the sandbox used Python 3.12.12 to install `.[dev]`; 10/10 tests, Ruff after formatting-only test fixes, `pip check`, and `/health/live` passed. GitHub pull-request CI also passed on standard Python 3.12 ([run 38693744680](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38693744680)). P01-T01 is complete; no gameplay code was added. Pull request #1 remains open for owner review.

## Completed in repository

- Initial repository baseline and development/security guidance.
- Master phase plan and immediate next-task definition.
- P00-T02 payout/settlement specification records total-payout multipliers, player-private bet data, per-number straight-up/split exposure caps, all confirmed per-selection caps, chip denominations, duplicate records, local-draft editing, immutable accepted bets, rebet rules, round timing, player-disconnect behavior, owner-selected atomic settlement/refund recovery, and standard European layout.
- Owner's specification choices and approval recorded on 2026-10-14.
- Owner-approved canonical legal-position catalogue with fixed red/black sets and expected counts.
- Cap/partial-acceptance edge-case matrix covering acceptance, exposure caps, concurrency, cutoff, normalization, idempotency, rollback, rebet, insufficient balance, and settlement/refund.
- Added deterministic JSON fixture tests/fixtures/roulette_catalogue.json, including all canonical inside selections, outside sets, red/black sets, and expected catalogue counts.
- Added standard-library test suite tests/test_roulette_catalogue_fixture.py to compare fixture data with independently generated expected combinations and validate catalogue counts/color coverage.
- Owner-reported local test evidence on 2026-10-14: `python -m unittest discover -s tests -v` completed with 8 tests passed and 0 failures.
- Reviewed PA-01 through PA-23 against locked requirements. Clarified PA-05 as a defensive invariant test because 1–4 coins of remaining cap capacity cannot occur through valid multiples-of-5 operations. Clarified PA-07/PA-08 so split bets are limited by constituent-number exposure; no separate exact-split cap is in the locked requirements. The matrix now maps scenarios to unit, database/transaction, concurrency, cutoff, rebet, settlement/refund, and authorization test layers.
- Added `roulette/BETTING_ENGINE_ARCHITECTURE_AND_TEST_PLAN.md` with proposed server components, transaction sequences, round state machine, and test layers.
- Added Python project metadata, a minimal FastAPI liveness endpoint, API smoke tests, a Python test/lint workflow, and local setup instructions for P01-T01. Owner's earlier Python 3.14.4 attempt was blocked; on 2026-10-15 a separate sandbox with Python 3.12.12 passed editable installation, 10/10 tests, Ruff, `pip check`, and HTTP 200 liveness. CI passed on pull request #1 on 2026-10-15.

- P02-T01 conceptual entity/transaction sketch and ten-finding technical self-review approved as a design baseline by the owner on 2026-10-16. No PostgreSQL schema or transaction behavior has been verified.
- P01-T03 PostgreSQL foundation files added with owner permission: localhost-only Compose, test-database connection check and CI setup/teardown. Docker is not available in this sandbox; GitHub CI connection evidence is pending.

## Current verification gates

- P01-T03: run the [Compose-based local PostgreSQL](../../infrastructure/README.md) startup and [isolated test database check](../../infrastructure/check_postgres.py) in CI, then record pass/fail and teardown. Docker is absent in this sandbox; no local Compose execution claimed.
- P02-T01: [technical self-review](database/P02_T01_DESIGN_REVIEW.md) records ten findings and draft corrections to lock ordering/session wording. Owner approved the conceptual baseline on 2026-10-16; this documentation task is complete, but findings remain to be addressed in future scoped tasks. No physical schema or transaction behavior is verified.
- Re-run the catalogue suite after any fixture/test changes; current reported evidence is 8/8 passing locally, and P01's full suite was 10/10.
- P01-T01 local and CI checks passed; it is complete. Owner's Python 3.14.4 environment separately still needs Python 3.12/3.13 to reproduce locally. GitHub Actions reported advisory notices for Node.js 20-based action versions and the upcoming `ubuntu-latest` image migration; review them in a future CI maintenance task.
- D-01 player/agent disablement and audited reassignment were approved; D-02 anonymization direction was approved while retention periods/backups/legal exceptions remain open. [D-10](decisions/2026-10-15-account-provisioning-and-point-flow.md) confirms single-owner provisioning, optional owner-managed players, owner-issued virtual points, conserved owner/agent/player transfers and owner-funded game-reserve direction. The exact POOL-01 coverage/global acceptance policy remains unapproved. The owner approved the **P02-T01 conceptual design baseline** on 2026-10-16. [Entity/transaction model](database/CONCEPTUAL_SCHEMA_AND_TRANSACTIONS.md), [review findings](database/P02_T01_DESIGN_REVIEW.md) and [task evidence](tasks/P02-T01.md) are recorded; no migrations or gameplay code have been authorized. P01-T02 frontend tooling and P01-T03 database environment remain future scoped tasks requiring separate permission.
- Before betting-engine implementation, use the documented architecture/test plan and implement tests for cap enforcement, balance reservation, concurrency, cutoff, rollback, idempotency, rebet atomicity, settlement, and void/refund against the actual implementation and supported database.
- Ensure future API/realtime authorization tests prove player-private bet data cannot be read by other players.
- Resolve remaining product/operations decisions before their dependent work: POOL-01 reserve coverage/global acceptance policy; D-06 round recovery; D-02 retention windows/backup/deletion exceptions; D-03 owner MFA recovery/session policy; D-04 performance/availability targets. D-01 removal and D-10 owner/agent/player transfer flow are approved, though not implemented.

## Important status distinction

The owner approved the payout/settlement specification and canonical legal-position catalogue on 2026-10-14. Catalogue fixture tests are reported passing (8/8), and the PA matrix review is recorded. A minimal API foundation passed sandbox-local and pull-request CI verification. Cap/partial-acceptance and production behavior remain unimplemented and unverified; no betting-engine implementation has been written. Do not mark P00-T02 complete until the remaining gates and acceptance criteria have recorded evidence.

## Status update rule

After each completed task, update this file and NEXT_ACTION.md. Mark a task complete only when its acceptance criteria and verification evidence are recorded. Never infer success from code generation alone.
