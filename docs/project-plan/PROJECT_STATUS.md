# Project Status

**Current phase:** P01 — Repository foundation (engine core also implemented ahead of plan, at owner request)  
**Current task:** P01-T01 — close out locally; then review the engine core and proceed to authentication (P03)  
**Implementation status:** FastAPI liveness foundation plus roulette engine core (catalogue, payouts, caps, wallet/ledger, bet acceptance, rebet, round close/settle/void/recovery, PostgreSQL schema and migration). No HTTP routes for betting, no authentication, no realtime, no web apps yet.  
**Specification status:** Payout/settlement specification and canonical legal-position catalogue approved by owner on 2026-10-14  
**Verification status:** Engine core verified in an independent Claude sandbox (Python 3.12.3, PostgreSQL 16.15): 233 tests passing, Ruff clean, clean-room rebuild repeated, concurrency/property tests green 8 consecutive runs. NOT yet verified on the owner's machine, in GitHub Actions, or with Docker Compose.  
**Last updated:** 2026-10-20

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

## Engine core added 2026-10-20 (implemented; awaiting owner-side verification)

Delivered under `services/api/` with tests in `tests/`:

- `roulette/catalogue.py`, `payout.py`, `caps.py`: pure rules, validated against the owner-approved fixture (not against themselves). Strict canonical selection keys (e.g. `split:17-20`; leading zeros and diagonals rejected).
- `db/models.py`, `migrations/versions/0001_initial_schema.py`: integer-point money, append-only ledger, non-negative wallets, per-exposure 2,000 CHECK, terminal-round and immutable-outcome triggers, immutable accepted bets. A test fails if models and migration drift apart.
- `wallet/service.py`: account/wallet creation, audited admin adjustments (reason mandatory, idempotent), ledger reconciliation query.
- `roulette/betting.py`: `place_bet` and `rebet`; one atomic, idempotent transaction; lock order round -> wallet -> exposure rows (ascending) so deadlocks cannot occur by construction.
- `roulette/rounds.py`: `close_round` (outcome persisted once, secure RNG with no inputs), `settle_round`, `void_round`, `recover_round`.
- `db/session.py`: transaction runner that retries deadlock/serialization failures and never retries domain errors.
- `core/errors.py` (stable error codes), `core/config.py` (fail-fast settings; placeholder secrets rejected in staging/production).

Evidence recorded (independent sandbox, 2026-10-20): 233 tests = 85 domain/catalogue-vs-fixture, 65 betting (all PA-matrix cap/partial/cutoff/idempotency/rebet cases), 33 round/settlement/void/recovery (including simulated mid-settlement crash), 26 schema/guard, 8 real multi-threaded contention, 1 property-based test against an independent payout oracle, 5 retry-runner, 8 original fixture, 2 API smoke tests. Mutation check: three deliberately injected bugs (wrong multiplier, stake double-credited on win, cap ignored) were each caught by the suite.

### Assumptions and open items for the owner

1. **Number-cap scope (needs confirmation):** the 2,000-coin straight-up/split cap per underlying number is implemented **per player, per round**, matching the per-selection caps and the player-privacy rule. If the owner intends a table-wide cap shared by all players, this must change and would let one player's bets affect another's acceptance.
2. **Payout convention:** implemented exactly as approved (total payout includes stake; an even-money win returns only the stake). Owner should confirm this is the intended player experience.
3. **Round timing:** `close_round` refuses to close before `closes_at`. Seconds 45-49 remain open for bets, per the locked requirements; `MASTER_PLAN.md` still shows older timing wording.
4. **Authorization is not implemented** (P03/P04): `admin_adjust` and the services trust their caller. They must never be exposed over HTTP without role checks.
5. **Unverified artifacts:** `docker-compose.yml` and the updated GitHub Actions workflow were syntax-checked only; they have not been run.
6. **Python version:** the owner's Python 3.14.4 is still outside the declared `<3.14` range; use a Python 3.13 virtual environment, or revisit the pin deliberately.

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
