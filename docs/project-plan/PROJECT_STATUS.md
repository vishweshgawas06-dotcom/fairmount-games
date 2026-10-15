# Project Status

**Current phase:** P02 conceptual design (no schema implementation)

**Current task:** P02-T01 design draft delivered for owner/technical review; no implementation authorized
**Implementation status:** Initial FastAPI liveness foundation committed; betting engine not started  
**Specification status:** Payout/settlement specification and canonical legal-position catalogue approved by owner on 2026-10-14  
**Verification status:** P01 foundation: 10/10 tests, Ruff, pip check and HTTP liveness passed locally; GitHub Python 3.12 pull-request CI passed. P02-T01 design review pending; no database tests or code.
**Last updated:** 2026-10-15

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

## Current verification gates

- P02-T01: obtain owner/technical review of the conceptual model and open decisions. It is documentation-only and remains open; no PostgreSQL implementation or transaction claims.
- Re-run the catalogue suite after any fixture/test changes; current reported evidence is 8/8 passing locally, and P01's full suite was 10/10.
- P01-T01 local and CI checks passed; it is complete. Owner's Python 3.14.4 environment separately still needs Python 3.12/3.13 to reproduce locally. GitHub Actions reported advisory notices for Node.js 20-based action versions and the upcoming `ubuntu-latest` image migration; review them in a future CI maintenance task.
- D-01 player/agent disablement, player wallet freeze, accepted-bet settlement and immediate audited agent reassignment were approved on 2026-10-15. D-02 verified anonymization direction was approved, while exact retention windows, backups and legal exceptions were deliberately deferred. [Decision records](decisions/README.md) capture scope and follow-ups. The owner separately authorized **P02-T01 conceptual design only**. [Draft entity/transaction model](database/CONCEPTUAL_SCHEMA_AND_TRANSACTIONS.md) and [review checklist](tasks/P02-T01.md) are awaiting owner/technical review; no migrations or gameplay code have been authorized. P01-T02 frontend tooling and P01-T03 database environment remain future scoped tasks.
- Before betting-engine implementation, use the documented architecture/test plan and implement tests for cap enforcement, balance reservation, concurrency, cutoff, rollback, idempotency, rebet atomicity, settlement, and void/refund against the actual implementation and supported database.
- Ensure future API/realtime authorization tests prove player-private bet data cannot be read by other players.
- Resolve remaining non-blocking product/operations decisions: user/agent removal and point-accounting behavior; historical record retention/anonymization/deletion; owner MFA recovery/session policy; measurable performance/availability targets.

## Important status distinction

The owner approved the payout/settlement specification and canonical legal-position catalogue on 2026-10-14. Catalogue fixture tests are reported passing (8/8), and the PA matrix review is recorded. A minimal API foundation passed sandbox-local and pull-request CI verification. Cap/partial-acceptance and production behavior remain unimplemented and unverified; no betting-engine implementation has been written. Do not mark P00-T02 complete until the remaining gates and acceptance criteria have recorded evidence.

## Status update rule

After each completed task, update this file and NEXT_ACTION.md. Mark a task complete only when its acceptance criteria and verification evidence are recorded. Never infer success from code generation alone.
