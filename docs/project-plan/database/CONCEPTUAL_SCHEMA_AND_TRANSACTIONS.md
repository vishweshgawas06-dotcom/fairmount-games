# P02-T01 — Conceptual PostgreSQL schema and transaction design

**Status:** Proposed for owner/technical review, not approved for implementation.

**Scope:** Entity/relationship and concurrency design only. No SQL, ORM model, migration, API, wallet, roulette or UI code is authorized by this document. The owner approved this *design task*, not its proposed schema choices. PostgreSQL is the planned accounting source of truth; Redis, if later used for fan-out, must not hold authoritative point or round state.

## 1. Sources of truth and design invariants

- [Locked requirements](../LOCKED_REQUIREMENTS.md), [D-01](../decisions/2026-10-15-account-disable-and-reassignment.md), [partially open D-02](../decisions/2026-10-15-privacy-deletion-and-retention.md), [approved payout rules](../roulette/PAYOUT_AND_SETTLEMENT_SPEC_DRAFT.md), [legal-position catalogue](../roulette/LEGAL_POSITION_CATALOGUE_REVIEW.md), and [engine test plan](../roulette/BETTING_ENGINE_ARCHITECTURE_AND_TEST_PLAN.md) govern behavior. Proposed DB structure below must not change those rules.
- V1 uses integer virtual points, never floats or real-money units. Wallet and ledger movements must reconcile; accepted bets are immutable; no balance or stake may be spent twice. A player begins with zero points.
- One global server-authored round and at most one persisted 0–36 outcome for that round; outcome generation independent of bets, identities, stakes and balances. The animation cannot write results.
- Individual bet/ledger records are private to the player and authorized operators. Public events contain shared round state only.
- Terminal accounting states `SETTLED` and `VOID_REFUNDED` are mutually exclusive. A committed settlement pays once and is never refunded; an uncommitted settlement that cannot safely complete is voided and refunded exactly once. Persisted outcomes are never replaced.
- This is a **logical design**: proposed names, data types, locks and constraints require a small PostgreSQL proof and migration review before becoming implementation decisions.

## 2. Entity relationship sketch

```text
owner/agent/player account ──1:1── private_identity
        │  │                     (name, mobile, authentication details separated)
        │  ├──1:N── session
        │  ├──1:1── wallet ──1:N── ledger_entry
        │  ├──1:N── agent_assignment_history (player; current agent derived from one active row)
        │  ├──1:N── audit_event (actor and/or target)
        │  └──1:N── bet ──N:1── round ──1:0..1── outcome
        │            │             └──1:N── round_event / lifecycle audit
        │            └──1:N── ledger_entry (stake, payout OR refund)
        ├──1:N── agent_budget / budget_entry (allocation authority; model pending review)
        └──1:N── idempotency_operation

(player, round) ──1:N── exposure_counter (per-number OR exact canonical selection)
```

Arrows describe intended relationships, not physical schema or authorization. Keep `private_identity` logically separate from durable accounting references. A stable opaque ID alone is **not** proof of anonymization if it remains linkable to a person.

## 3. Proposed record groups and key constraints

| Group | Minimum proposed fields / relationship | Integrity and access design |
|---|---|---|
| `account` | Opaque PK; role (`OWNER`, `AGENT`, `PLAYER`), status, created/disabled timestamps, actor reference. Link to private identity. | No cascade delete of accounting records. Restrict role transitions; player may have one current assigned agent. Disabled login/betting forbidden, but accepted obligations settle. Any owner/admin taxonomy beyond V1 needs review. |
| `private_identity` | Account FK, name, mobile, credential hash and recovery/MFA references where relevant. | PII partition allows later reviewed anonymization. Unique mobile policy and reassignment after anonymization require a separate approval; never store plaintext passwords. Minimize personal fields in audit, logs, bet and ledger tables. |
| `agent_assignment_history` | Player, agent, effective start/end, owner actor and audit reference. | At most one current assignment per player (partial uniqueness plus transaction checks). Preserve historical attribution, never backdate or rewrite bet/ledger records on reassignment. Test same-player concurrent reassignment. |
| `session` | Account, opaque session identifier/token hash, created/expires/revoked, optional device context. | No raw session token in DB or logs. Revoke on disablement; one active *player* session must be enforced safely under concurrent logins. MFA session design awaits D-03. |
| `wallet` | One per player; integer `balance >= 0`; row version optional. | Balance is a transactional projection of immutable ledger movements. Disabled player's balance remains frozen for initiated actions but accepts committed settlement/void credits. Never overwrite for admin correction. |
| `ledger_entry` | Opaque ID, wallet, signed integer delta, kind (`BET_STAKE`, `BET_PAYOUT`, `BET_VOID_REFUND`, admin credit/debit, etc.), actor/target, round/bet reference, reason/correlation key, timestamp. | Immutable entries; `wallet.balance = initial balance + sum(delta)` for that wallet. Unique effect reference per operation/kind (one stake, one payout or refund per bet); positive result credits use approved **total-return** multiplier, e.g. 10 straight-up → 350 total credit. Gameplay P/L = sum(gameplay deltas), separately from admin allocations. Terminal exclusivity is guarded by round transaction lock/state, not uniqueness alone. Admin adjustments require reason and audit. |
| `agent_budget` + `budget_entry` | Agent, available/committed allocation capacity and immutable budget movement history with owner actor/reason/reference. | **Provisional representation only:** D-01 requires unused capacity returned to owner with audit, no creation/loss of points. Whether budgets are transferable wallet-like points or an allocation ceiling is still a product/accounting choice; no budget migration until chosen. Disable/reassign must lock and reconcile without changing player wallet history. |
| `round` | Opaque PK, monotonically ordered round sequence, authoritative UTC start/cutoff/reveal timestamps, state, worker/lease fields only if later approved, terminal reason and timestamps. | At most one current global round, guarded by a reviewed unique/leader strategy. Time read from server/DB, never client. Betting closes at second 50; result/reveal at second 60. State-transition constraints/transaction tests prevent both terminal states. |
| `outcome` | Unique round FK, number integer 0–36, generated/persisted time, non-secret method/version and audit reference. | At most one outcome per round, never update/regenerate. Only RNG service writes it, independently of bet data. Pre-reveal access restricted; audit cannot leak result early. Exact RNG and timing/worker recovery design awaits D-06. |
| `bet` | PK, player FK, round FK, canonical type+selection key and catalogue version, accepted integer stake, request/rebet operation FK, accepted timestamp, original agent attribution if needed. | Stake >=5 and divisible by 5; unique bet ID, **not** unique(player, round, selection): duplicates remain separate. Immutable accepted amount/selection; settle state derived from terminal round plus effect entries or an atomic projection. Store requested/returned cap-excess in idempotent response, not as a bet. Private visibility enforced in API/realtime. |
| `exposure_counter` | Player+round+kind+canonical key, amount used. `NUMBER` keys 0–36 for straight-up/split; `EXACT` keys for the approved street/corner/six-line/first-four/outside types. | Unique counter per key; `0 <= used <= 2000`. A split increments *both* number counters by its accepted stake; no separate exact-split cap. Duplicates share an exact-selection counter. Counters must reconcile to immutable accepted bets; do not rely on cache or client totals. |
| `idempotency_operation` | Authenticated actor/account, operation kind, client key, request fingerprint, response/result reference, state/timestamps. | Unique(actor, operation, key), reject reused key with different payload. Record the response and accounting effects in the **same** transaction; same-key concurrent requests wait/return original result, not create duplicates. Scope and cleanup retention still need review. |
| `audit_event` / `round_event` | Actor, target, action, reason, correlation ID, time, non-sensitive before/after references, round lifecycle/void cause. | Append-only in normal paths, restricted reads; omit password/token/mobile. Owner/agent actions, account handoff, changes, failure and void are auditable. Subject to D-02 retention and access review. |

The `bet` table may represent accepted bets only; rejected submissions have an idempotent response but **no** wallet, bet, exposure or ledger changes. For cap-limited partial acceptance, if the system debits only the accepted amount, “return the excess” means it is never debited and the response states requested/accepted/excess. Whether a separate informational ledger line is wanted is open; never debit full stake and leave a transient externally visible deficit. Client drafts have no persistent bet records.

## 4. Proposed PostgreSQL invariants and indexes (review before migrations)

- Primary/foreign keys, `NOT NULL`, role/state check constraints or safe enums, positive bounded point values, and nonnegative wallet/counter/budget projections. Integer width must accommodate aggregate balances and winnings without overflow; validate upper bounds before choosing `BIGINT` and transaction arithmetic.
- Unique: one wallet/private identity per account; one outcome per round; `(player, round, kind, canonical_key)` for exposure; `(actor, operation_kind, idempotency_key)`; one effect `(bet_id, effect_kind)` for stake/payout/refund, with terminal lock/state to prevent payout **and** refund; one active player session/current assignment/global round using reviewed partial unique indexes or equivalent.
- Lookup indexes: active round sequence/state/cutoff, bets by `(round, player)` and `(player, round)`, ledger by wallet/time and round/bet, sessions by account/expiry, assignment by agent/current state, counters by player/round, idempotency by actor/key. Avoid indexing raw mobile in broadly readable schemas/logs; private identity unique lookup requires scoped access.
- Consistency involving rows (wallet vs ledger, two split counters vs bet, round terminal state vs all players' entries) cannot be guaranteed by simple `CHECK` constraints alone. Enforce via reviewed transactions, row locks, unique effect references, reconciliation jobs and failure-injection tests. No unconditional cascade deletes for durable accounting.
- Migration order proposal: accounts/private identity/assignment/session; wallet/ledger/budget after accounting policy; rounds/outcomes; bet/idempotency/exposures; audits. Each migration needs fresh DB up/down or forward-repair evidence and compatibility review. **No migration is written in P02-T01.**

## 5. Transaction sketches and locking order

These are **candidates**, to be measured on PostgreSQL with multiple connections. Never rely on in-process mutexes. Use one lock-order policy within each operation, document exceptions and test deadlock/retry behavior. At minimum: resolve authenticated identity; lock the relevant round/terminal state as needed; lock account/session or ownership row; lock wallets and budget rows in stable ID order; lock exposure keys in sorted canonical order; write effects and idempotent response; commit. Creating an absent counter concurrently requires an insert/upsert or pre-seeded row protocol so `SELECT FOR UPDATE` on a missing row does not falsely provide a lock. A per-round lock can simplify cutoff ordering but could bottleneck all players: measure before finalizing.

### A. Player bet acceptance

1. Authenticate and verify active player session; resolve/create the idempotency operation under its unique key. If previously committed with matching fingerprint, return the original response. Reject mismatched payload on key reuse.
2. Read/lock authoritative round versus cutoff transition; check server time and committed cutoff, account enabled status and legal canonical selection. No submitted client timestamp can override cutoff.
3. Lock player's wallet and applicable exposure counters; verify wallet covers **full requested** ordinary stake first. Reject with no accounting effects if it cannot. Apply all relevant per-number/exact-selection caps; accept largest valid multiple of 5 not less than 5 or reject.
4. Insert accepted bet (separate record even if duplicate), increase counters, debit only accepted amount and insert `BET_STAKE` ledger effect; persist requested/accepted/excess response and commit together. Non-bet rejection may be cached idempotently but never mutate wallet/cap/bet. Ensure wallet/ledger/exposure reconciliation and rollback on any write failure.

### B. All-or-nothing rebet

Read only the authenticated player's complete prior-round accepted set in stable order. Lock cutoff/wallet/all distinct counters in deterministic order, validate *every* requested amount at full size and total balance, then insert the whole set/aggregate counters/ledger and one idempotent response in one transaction. Any unavailable cap, insufficient balance or failure rolls back all repeated bets; do not apply cap-limited partial acceptance to rebet items.

### C. Cutoff, result, settlement and void/refund

At second 50 the server commits cutoff and freezes accepted bets; at or before animation it persists an independently generated outcome exactly once under the round's unique result key. At second 60, one transaction locks round terminal state, checks persisted outcome, calculates the approved total return on all winning bets, locks all affected wallets in stable order, writes uniquely referenced payout effects, credits balances and marks **the whole global round** `SETTLED` in one commit. Losing stakes already debited at acceptance remain losses. Do not publish a settled result before the terminal commit.

If a settlement cannot commit safely, a competing/repair transaction must observe committed state first: if `SETTLED`, do nothing; otherwise lock the round, write one refund effect for **each** accepted bet, credit wallets, record cause and commit `VOID_REFUNDED` atomically. No payout and refund for the same round. Retain a persisted outcome even for a voided round. What qualifies as irrecoverable failure, how long to retry, and behavior if no outcome was ever persisted are **D-06 open**; do not implement an arbitrary timeout or invent a result. Large global all-player transactions may exceed acceptable lock time; do not weaken the owner's atomic rule without an explicit new decision.

### D. Account disablement / agent reassignment / admin allocation

Disablement locks account/session and marks active sessions revoked; it blocks new user/agent actions but leaves existing accepted bets and settlement writes valid. Agent reassignment locks current assignment and participant authorization rows, ends old assignment and starts new assignment with audit in one transaction; do not rewrite historical agent/actor references. Disabled player balances remain frozen for player-initiated actions, not for obligated settlement/refund. Agent-budget return, player allocations and owner adjustments lock the relevant budget and wallet rows, write ledger/budget/audit entries with a required reason and idempotent reference in one transaction; the exact source-of-points accounting model remains undecided.

## 6. Ownership, privacy, retention and API boundaries

- Database FKs are **not** authorization. Player queries derive identity from validated session and filter by account; agent queries join only current assignments and respect disabled state; owner operations require privileged session/MFA policy. WebSocket authorization and reconnect use the same rules. Test cross-player/agent access and revoked sessions.
- Public round/outcome data never includes bet/ledger/wallet/person identifiers; private payloads target their authenticated recipient. Authenticated operator audit views are separately scoped and logged.
- D-02: separate PII to support eventual verified anonymization; preserve only records truly non-identifying after review. Do not set retention timers, expire idempotency/audit records, erase backups or design destructive jobs until exact periods/holds and legal exceptions are approved. Stable surrogate IDs can still be personal data if a mapping survives.
- Backups/restore, migrations, UTC times and key/secret handling must be tested in later phases; this document is not a privacy certification.

## 7. Verification matrix for future implementation (not tests run now)

| Layer | Required evidence |
|---|---|
| Schema/migrations | Fresh PostgreSQL migrate, FK/unique/check violations, safe rollback/forward migration, no ledger cascade delete, seeded reconciliation. |
| Unit/catalogue | Approved fixture and payout examples including zero; PA-01–PA-10/PA-14–PA-16/PA-20–PA-21. |
| Transaction | Failure at each write boundary proves no partial wallet/bet/exposure/response; PA-17/PA-18; all-or-nothing PA-19; settlement and void PA-22/PA-23. |
| Concurrency | Multiple PostgreSQL connections race same wallet, split+straight number cap (PA-11), duplicate exact cap (PA-12), absent counter creation, cutoff (PA-13), settlement vs void, agent reassignment and budget handoff. No overspend/double payout or deadlock left untreated. |
| Auth/privacy | Player cannot see another's bet or balance through HTTP/WebSocket; agent cannot manage former agent's player; disablement revokes sessions while accepted bets settle; PII restricted. |
| Operations | Recovery after process/DB interruption; outcome at most once; ledger/budget reconciliation; backup/restore and bounded round settlement measured against later SLOs. |

## 8. Open decisions and exit gate

| ID | Decision needed before | State |
|---|---|---|
| D-02 | Final data lifecycle/destructive migration and launch | Retention durations, eligibility/holds, backup expiry and legal review deferred by owner. Conceptual separation may proceed. |
| D-03 | MFA/session recovery implementation | Owner MFA recovery, session expiry/privileged reauthentication not yet approved. |
| D-06 | Round/worker migration and engine implementation | RNG/audit choice, outcome persistence timing, leader/cutoff ordering, failure/retry/void trigger and missing-outcome handling. Approved phase timings/outcome independence cannot be changed. |
| ACCT-01 | Budget/ledger migrations and point allocation | Owner chooses whether agent budgets are funded balances (conserved transfers) or authorization ceilings (with explicit issuance accounting); define original point issuance, unused-return and reconciliation before code. No assumption here. |
| PRIV-01 | Identity schema and deletion workflow | Mobile uniqueness/reuse after anonymization, login effects, verification and irreversible de-identification plan. |
| OPS-01 | Global settlement implementation and P17 | Size/latency targets and PostgreSQL locking strategy for atomic all-player settlement; test real scale, never silently switch to partial settlement. |

**P02-T01 review gate:** Owner/technical reviewer confirms entity boundaries, transaction ordering and the open-decision register. Evidence is a reviewed document and explicit disposition of findings. This task does **not** claim migration viability, runtime concurrency safety, compliance, or that any database code/tests have been run. After review, request a separate, scoped task for PostgreSQL environment/schema implementation; do not advance to it automatically.
