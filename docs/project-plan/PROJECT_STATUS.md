# Project Status

**Current phase:** P01 — Repository foundation  
**Current task:** P01-T01 — Establish and verify the Python API foundation  
**Implementation status:** Initial FastAPI liveness foundation committed; betting engine not started  
**Specification status:** Payout/settlement specification and canonical legal-position catalogue approved by owner on 2026-10-14  
**Verification status:** Catalogue suite reported passing locally (8/8); PA-01–PA-23 reviewed; API foundation committed; owner-reported verification attempt blocked because local Python is 3.14.4 but project requires Python >=3.12,<3.14; API tests, lint, and endpoint remain unverified  
**Last updated:** 2026-10-15

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
- Added Python project metadata, a minimal FastAPI liveness endpoint, API smoke tests, a Python test/lint workflow, and local setup instructions for P01-T01. Owner-reported local attempt on 2026-10-15: installation rejected Python 3.14.4 against the project's `<3.14` constraint; all 8 catalogue tests passed, API smoke tests could not import FastAPI, and Ruff/Uvicorn were unavailable. API/lint/endpoint verification remains blocked and unverified.

## Current verification gates

- Re-run the catalogue suite after any fixture/test changes; current reported evidence is 8/8 passing locally.
- Unblock P01-T01: owner reported on 2026-10-15 that install failed because active Python is 3.14.4, outside the declared `>=3.12,<3.14` range. Eight catalogue tests passed; API test import failed because FastAPI was not installed; Ruff and Uvicorn were unavailable. Run `py -0p`, create a `.venv` with Python 3.13 if installed (otherwise install Python 3.13), install `.[dev]`, then rerun full tests, Ruff, and `/health/live`.
- Before betting-engine implementation, use the documented architecture/test plan and implement tests for cap enforcement, balance reservation, concurrency, cutoff, rollback, idempotency, rebet atomicity, settlement, and void/refund against the actual implementation and supported database.
- Ensure future API/realtime authorization tests prove player-private bet data cannot be read by other players.
- Resolve remaining non-blocking product/operations decisions: user/agent removal and point-accounting behavior; historical record retention/anonymization/deletion; owner MFA recovery/session policy; measurable performance/availability targets.

## Important status distinction

The owner approved the payout/settlement specification and canonical legal-position catalogue on 2026-10-14. Catalogue fixture tests are reported passing (8/8), and the PA matrix review is recorded. A minimal API foundation is committed but awaits local verification. Cap/partial-acceptance and production behavior remain unimplemented and unverified; no betting-engine implementation has been written. Do not mark P00-T02 complete until the remaining gates and acceptance criteria have recorded evidence.

## Status update rule

After each completed task, update this file and NEXT_ACTION.md. Mark a task complete only when its acceptance criteria and verification evidence are recorded. Never infer success from code generation alone.
