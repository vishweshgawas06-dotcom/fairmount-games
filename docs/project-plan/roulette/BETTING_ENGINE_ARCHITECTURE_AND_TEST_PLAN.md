# FairMount Roulette — Betting Engine Architecture and Test Plan

**Status:** Historical design proposal, updated for [D-06a](../decisions/2026-10-24-round-result-recovery.md); private engine/worker/ledger slices now have PostgreSQL CI evidence, but no public betting API or deployment.
**Phase:** P00/P01 planning boundary  
**Purpose:** Preserve testable invariants and remaining gates without treating superseded failure-void wording as authority.

## 1. Non-negotiable invariants

1. The server is authoritative for round state, cutoff, accepted bets, wallet balances, outcome, and settlement.
2. One persisted outcome is shared by all players in a round. Outcome generation is independent of bets, balances, and player identity.
3. A client timer or wheel animation never decides acceptance or outcome.
4. Accepted stakes are immutable. Draft edits/cancellations remain client-side until submission.
5. An ordinary request is rejected in full if balance is below the full requested stake. Do not accept a balance-limited partial bet.
6. Cap-limited partial acceptance is allowed only when the wallet can cover the full requested stake. Accepted amount must be at least 5 and a multiple of 5.
7. The 2,000-coin per-number exposure cap applies to straight-up and split bets. A split consumes exposure on both constituent numbers. The locked requirements do not define a separate exact-split cap.
8. Exact-selection caps apply to the locked list: Red, Black, each dozen, each column, each street/row, Odd, Even, each corner, each six-line, First Four, and each Low/High selection. Duplicate records aggregate against the same exact selection cap.
9. A rejected request has no wallet, ledger, bet-record, or exposure side effects.
10. Every acceptance, rebet, settlement, and void/refund path must be atomic and idempotent.
11. Player bet data is private; public round messages may contain the shared phase, countdown, result, and winning-number history, but not other players' bet details.

## 2. Proposed server-side components

- **Round service:** owns round lifecycle and authoritative phase/cutoff timestamps.
- **Bet acceptance service:** validates canonical selection, stake, balance, cutoff, caps, and idempotency.
- **Wallet/ledger service:** performs transactional point movements with reason/type, round ID, bet ID, and idempotency key.
- **Settlement service:** calculates total-return payouts from persisted outcome and accepted bets; writes payout ledger entries and terminal state atomically.
- **Recovery worker:** examines non-terminal rounds; after cutoff persists an independent missing result once, or reuses the persisted result, then retries settlement even if late. No automatic timeout/failure void; exceptional void requires a separate authorized incident policy.
- **Private player query/realtime layer:** filters own bet records by authenticated player identity; never trusts a player ID supplied by the client for authorization.
- **Admin/agent audit layer:** keeps point adjustments separate from gameplay P/L and requires a reason for administrative adjustments.

Use the existing planned stack: FastAPI/Python, PostgreSQL, SQLAlchemy 2, Alembic, and WebSockets. Redis may support fan-out or coordination, but PostgreSQL transactions/constraints remain the accounting source of truth.

## 3. Acceptance transaction sequence

Within one database transaction:

1. Authenticate the player and verify account/session eligibility.
2. Resolve the idempotency key. If already processed, return the stored original response without repeating mutations.
3. Lock/read the authoritative round row and reject if the server cutoff has committed.
4. Validate the bet type and canonical selection against the approved catalogue. Normalize unordered number sets before looking up aggregate exposure.
5. Validate requested stake: integer, at least 5, and divisible by 5.
6. Lock the player's wallet row and verify balance covers the **full requested stake**. If not, reject with no mutation.
7. Lock all relevant cap/exposure rows in deterministic key order. For straight-up/split, inspect each constituent number's remaining exposure. For a selection with an exact-selection cap, inspect that canonical selection's remaining cap.
8. Compute the largest accepted amount not exceeding the request and every applicable remaining cap, rounded down to a multiple of 5. If below 5, reject with no mutation.
9. Atomically record the accepted bet and exposure, reserve/debit the accepted amount, and record any cap-excess return/ledger detail required by the accounting model. The final wallet decrease must equal the accepted amount, and no intermediate partial state may commit.
10. Persist the idempotent response and commit. Any failure rolls back the entire operation.

Implementation must decide and document exact row/table locking and database constraints before coding. Concurrent acceptance must serialize on shared wallet and exposure keys, not rely on application-memory locks.

## 4. Rebet transaction sequence

- Read the authenticated player's complete previous-round accepted bet set.
- Validate that the current round is still open.
- Compute the full set's requested total and reject the entire rebet if the wallet cannot cover it.
- Validate every selection and calculate all applicable cap capacity as one operation.
- Rebet is all-or-nothing: if any item cannot be accepted at its full amount under current caps, reject the whole rebet. Do not use cap-limited partial acceptance for individual rebet items.
- Lock wallet and all relevant exposure rows in deterministic order; reserve all stakes and create all accepted records atomically.
- Store one idempotent operation result. A retry must not duplicate any bet or debit.

## 5. Round and settlement state machine

Use an explicit, constrained state machine. Suggested terminal states are `SETTLED` and `VOID_REFUNDED`; a round may not reach both.

- Seconds 0–44: betting open.
- Second 45: final-bet call is shown; betting remains open.
- Second 50: server commits betting cutoff/freeze; animation begins.
- Second 60: reveal the persisted outcome and settle.
- Persist the outcome once. Recovery must never generate a replacement outcome if one already exists.
- Settlement transaction locks the round, calculates every player's winning total return, writes idempotent payout ledger entries, credits wallets, and marks the round `SETTLED` in one commit.
- Winning multipliers are total-return multipliers: for example, a 10-coin straight-up win credits 350 total. Since stake was already reserved, do not add the stake a second time.
- If a result has not persisted after cutoff, select it independently and persist once, then retry settlement even after the nominal reveal time. If a result has persisted but settlement fails, retain it and retry that same result; never reroll, auto-void or refund it.
- If settlement committed, retries/recovery workers must observe `SETTLED` and do nothing. `VOID_REFUNDED` is reserved for a separately authorized, audited exceptional incident policy while no result has persisted; a timeout or failed settlement alone does not authorize it.
- Use unique ledger/idempotency constraints and row locks to prevent duplicate payout/refund under concurrent workers.

## 6. Test layers and mapping to PA matrix

### Pure unit tests
- PA-01–PA-10: accepted amount, excess return, per-number exposure, exact-selection aggregation, duplicate records, minimum and multiple-of-5 rules.
- PA-14–PA-16: reject invalid catalogue geometry, normalize order-independent selections, distinguish bet types.
- PA-20–PA-21: reject ordinary requests when full requested stake exceeds balance, with no side effects.
- PA-05: defensive invariant test only; a 1–4 coin capacity is unreachable through valid multiples-of-5 operations.

### Database integration tests
- PA-17: repeated idempotency key returns original response without duplicate ledger/bet/wallet movement.
- PA-18: inject failure at each write boundary and prove full rollback.
- PA-22–PA-23: late/missing-result recovery, retry after failed settlement with the same persisted result, terminal-state exclusivity, exactly-once accounting, and exceptional void/refund primitives **only** under a separately approved incident policy.

### Concurrency tests
- PA-11: overlap straight-up and split requests sharing a number; exposure must never exceed 2,000.
- PA-12: overlap duplicate outside selections; exact-selection cap must never exceed 2,000.
- Run with multiple real database connections/processes against PostgreSQL; an in-memory test double is insufficient evidence.

### Lifecycle and composite-operation tests
- PA-13: cutoff committed server-side rejects a request even when the client timer says open.
- PA-19: rebet rejects as a whole for insufficient balance or any cap conflict; no partial bets or wallet movement.
- Add races between cutoff and bet acceptance, and between settlement and recovery workers.

### API/realtime authorization tests
- Player A cannot fetch Player B's bets, amounts, personal game history, or private event payloads by changing IDs or subscribing to another player's channel.
- Public round updates contain only shared public fields.
- Test disabled users, stale sessions, unauthorized agents, and forced logout.

## 7. Evidence required before calling engine verification complete

- Catalogue fixture tests pass.
- All applicable PA tests pass against the actual service and supported PostgreSQL configuration.
- Concurrency tests demonstrate no cap overflow or double-spend.
- Failure-injection tests prove atomic rollback and idempotent recovery.
- Settlement and void/refund tests prove no player can receive both payout and refund for the same stake.
- API and realtime tests prove player-private data isolation.
- Test output, environment/database version, and any known limitations are recorded in the repository.

## 8. Explicitly out of scope

This document does not implement the engine, create database migrations, authorize real-money wagering, or resolve unrelated open operations decisions. Do not claim production readiness based on catalogue-only tests.
