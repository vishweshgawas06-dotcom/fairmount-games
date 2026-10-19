# FairMount Roulette — Detailed delivery plan (proposal)

**Status:** Delivery plan approved by owner on 2026-10-15; individual implementation tasks still require explicit permission.

**Prepared:** 2026-10-15

**Scope:** V1 virtual-points, single-zero European roulette only. No deposits, withdrawals, cash-equivalent prizes, or real-money gambling.

## How to use this plan

- [Locked requirements](LOCKED_REQUIREMENTS.md), the [owner-approved payout/settlement specification](roulette/PAYOUT_AND_SETTLEMENT_SPEC_DRAFT.md), and the [approved legal-position catalogue](roulette/LEGAL_POSITION_CATALOGUE_REVIEW.md) govern product behavior. This document proposes a delivery sequence, not new product rules. In particular, the approved **total-payout** multipliers are intentional: a winning 10-point straight-up bet credits 350 total, not 360.
- Existing task IDs P00-T02 and P01-T01 retain their current meaning/status. The owner approved this delivery sequence on 2026-10-15; all other task IDs below are **planning placeholders** until individually scoped and approved for implementation. No schedules, staffing assumptions, or completion claims are implied.
- For each proposed task, create a small task brief before work: allowed files/scope, prerequisites and unresolved choices, acceptance examples, failure cases, commands to run, and rollback/observability implications. Get owner permission before implementing it. Do not implement ahead of a blocked dependency.
- At every task: reproduce baseline; obtain permission for implementation; make one readable, bounded change with appropriate error handling; run unit/integration/security/UI tests as applicable and debug failures; review the diff and authorization/accounting impact; record commands, results, and environment; update task, `PROJECT_STATUS.md`, and `NEXT_ACTION.md`; request review; commit and push approved stage/checkpoint work to GitHub. Tests must run against the real implementation, not just the catalogue fixture. Follow [workflow rules](WORKFLOW_AND_UPDATE_RULES.md) for UI quality, verification, and reporting.
- A phase passes only after its gate has evidence. Tests are **continuous**, not postponed to P16. P15/P16 are broad hardening gates, not the first time recovery or security is tested. A failed gate keeps the task open.

## Owner decisions and design checkpoints

| Checkpoint | Decision/evidence needed | Needed before |
|---|---|---|
| D-01 | **Accepted 2026-10-15:** [disablement, settlement, frozen player wallet and audited agent reassignment](decisions/2026-10-15-account-disable-and-reassignment.md). Budget handoff implementation details remain to design. | Account/reassignment implementation in P03/P06/P07 |
| D-02 | **Partially accepted 2026-10-15:** [eligible verified anonymization with non-identifying audit retained](decisions/2026-10-15-privacy-deletion-and-retention.md). Exact retention periods, backup handling and legal review are open. | Final schema/data lifecycle and release in P18 |
| D-03 | **Partially accepted 2026-10-16:** [owner TOTP + one-time recovery codes, role-specific timeouts, 10-minute sensitive-action MFA, full session revocation](decisions/2026-10-16-owner-mfa-and-sessions.md). One active session per owner/agent/player is approved; manual all-factors-lost recovery remains open. | P03 auth/session design; production recovery gate |
| D-04 | Approve measurable availability, capacity, latency, reconnect, and recovery targets and measurement conditions. | P17 pass/fail and production readiness |
| D-05 | Review deployment jurisdiction, legal/privacy requirements, and public-facing virtual-points disclosures. This does **not** authorize real money. | Staging/production launch |
| D-06 | Define server-side round clock/cutoff commit ordering, worker ownership/failover, RNG method and audit evidence, outcome-persistence timing, and how the chosen void/refund policy is triggered/retried after failures. Must preserve approved 50-second cutoff, 60-second reveal, one outcome, and independent RNG. | P08 schema/service design |
| D-07 | Clarify any conflicting terminology in the cap matrix: PA-09's reference to a “split-selection cap” is not a separately approved exact-split cap. Follow the locked per-number split exposure rule unless the owner explicitly changes the specification. | Betting acceptance tests/code |
| D-08 | Choose API/realtime contract versioning, event ordering/replay, deployment shape and whether Redis is needed; PostgreSQL remains accounting source of truth. | P02/P09 integration design |
| D-09 | Review authentic European wheel pocket order/visual geometry, original visual/audio references and asset rights, target device/browser matrix, smoothness budget and reduced-motion presentation. Do not treat animation physics as outcome generation. | P12 visual design and P14 acceptance |
| D-10 / POOL-01 | [Owner-approved account/point-transfer flow](decisions/2026-10-15-account-provisioning-and-point-flow.md): one owner, owner-managed players allowed, owner-issued pool and conserved transfers; owner-funded game reserve direction. **Exact pre-bet coverage/global limit is still unapproved.** | P02/P05 wallet/ledger design; approve reserve rule before P08/P11 acceptance |
| D-11 / PRIV-01 | **Partially accepted 2026-10-16:** [global case-insensitive 3–32-character player username, generated unique Agent ID, reserved names, shared unverified mobile and temporary activation](decisions/2026-10-16-identifier-policy.md). Old username/Agent-ID reuse after anonymization remains open. | P03 registration/identity constraints; D-02 deletion/retention |

D-01 and the D-10 account/transfer flow are owner-approved. D-02 remains open for exact periods, deletion and legal review; D-11 resolves identifier uniqueness/contact use but defers reuse after anonymization. D-03 locks baseline MFA/session behavior while manual recovery remains open. D-04 remains unresolved. The D-10 game-reserve funding direction is approved, but POOL-01 coverage/limit details remain open. D-05–D-09 are proposed design/review checkpoints, **not** decisions already made. Record material approvals in `decisions/`; never guess values. The owner has confirmed a realistic-feeling European roulette machine as a product goal, including a smoothly spinning wheel and ball. UI reference images/videos may guide original visuals and interactions, but must not override approved game rules or introduce copyrighted assets. Asset ownership/licensing needs review before release.

## Dependency and milestone map

1. **M0 — specification and reproducible foundation:** P00 review + P01 verification. Catalogue/payout approval is recorded, but P00-T02 engine-behavior gates remain open. P01-T01 has not been fully verified.
2. **M1 — safe accounts and accounting:** P02 → P03 → P04 → P05; database schema and sessions must precede money-like point movements. P06/P07 can follow P05 independently of player visuals.
3. **M2 — authoritative game:** P08 → P09 and P11 server acceptance → P10/P11 client integration. UI can be prototyped against *clearly marked mock contracts*, but cannot be presented as working gameplay before the backend is verified.
4. **M3 — experience and resilience:** P12/P13/P14 after authoritative result and player contracts; P15 reliability tests expand the work done throughout M1/M2.
5. **M4 — release:** P16 → P17 → P18 → P19, subject to signed-off operational/legal decisions. Phase numbers are categories, not a rigid prohibition on parallel non-dependent work.

### P00 — Specification lock (existing phase; partially evidenced)

- **P00-T02 (existing):** Owner-approved payout/settlement and legal catalogue; fixture's 8 tests were previously reported passing. Remains open for actual engine, privacy, and transaction verification; do not claim those behaviors exist.
- **P00-T03 (proposed):** Reconcile stale plan/draft language with approved timing/catalogue, resolve D-07, and maintain a decision register. **Gate:** no contradictory instructions used as implementation requirements; disputed behavior goes to owner, not a developer assumption. **Evidence:** reviewed document diff and owner decisions where required.
- **P00-T04 (proposed):** Capture D-01–D-06 as scoped decision records with owners and before-phase checkpoints. **Gate:** no unresolved decision is silently implemented. **Evidence:** explicit accepted/proposed statuses.

### P01 — Repository foundation (current implementation task)

- **P01-T01 (existing, open):** Verify initial FastAPI liveness foundation. Use Python 3.12/3.13 (`py -0p` on Windows; inspect available interpreters on other systems), create a local virtual environment, install `.[dev]`, run `python -m unittest discover -s tests -v`, `python -m ruff check .`, start Uvicorn and check `/health/live`. **Gate:** reproducible install, full suite/lint/health and CI results recorded; liveness is not readiness.
- **P01-T02 (proposed):** Establish reproducible frontend workspace/toolchain only when client work is scoped; pin package manager/runtime, minimal build/type/lint/test commands; no placeholder green CI. **Gate:** clean clone runs documented checks.
- **P01-T03 (complete 2026-10-16):** [Local PostgreSQL foundation task](tasks/P01-T03.md): safe localhost-only Compose, isolated test database and connection check. No migrations or gameplay. **Gate:** clean GitHub CI checkout started/stopped Compose, verified test DB connection and passed Python tests/lint; local sandbox lacks Docker.

### P02 — Database and migrations

- **P02-T01 (design complete 2026-10-16):** [Conceptual schema/transaction design](tasks/P02-T01.md) and [technical review](database/P02_T01_DESIGN_REVIEW.md) were accepted as a planning baseline. They cover users/roles/ownership, sessions, wallet/ledger and reserve, rounds, bets, exposures, idempotency, audits, authorization and terminal accounting. D-02 retention, D-06 recovery and POOL-01 coverage remain open. **Gate passed for conceptual design only**; no physical schema, migrations or destructive cleanup authorized.
- **P02-T02a (complete 2026-10-16):** [First physical schema slice](tasks/P02-T02a.md) added account/identity/assignment models and one Alembic migration. Clean CI passed upgrade/downgrade/re-upgrade, metadata check and real PostgreSQL integrity tests. No login, wallet or gameplay; D-02 identity reuse/retention and D-03 security policy remain open.
- **P02-T02b and later (not authorized):** Add remaining SQLAlchemy 2 repositories/migrations in reviewable slices only after their decisions are resolved. **Gate:** fresh DB migration/recovery and relevant constraints/concurrency tested on PostgreSQL.
- **P02-T03:** Test migration upgrades from prior version and backup/restore rehearsal for local/test DB. **Gate:** data and schema survive documented upgrade and restore without production data exposure.

### P03 — Authentication and sessions

- **P03-T01a (approved design 2026-10-16):** [Registration/identifier contract](tasks/P03-T01a.md) defines owner/agent creation boundaries, exact username/Agent-ID formats, reserved names and temporary activation. **Gate:** owner approved contract; no code was authorized in this task.
- **P03-T01b (authorized narrow slice):** [Canonical identifier helpers and DB constraints](tasks/P03-T01b.md), migration and PostgreSQL tests only. **Gate:** CI upgrade/downgrade/metadata parity, canonical/invalid/duplicate tests. **Later tasks:** Role binding and password hashing primitives have since completed under the owner’s broad step-by-step permission. Provisioning, concurrent registration, credential activation and reset remain unimplemented; no self-registration or plaintext retrieval. **Gate:** PostgreSQL collision/concurrency, duplicate/disabled accounts and token/secret exposure tests.
- **P03-T01c (complete 2026-10-16):** [Role-binding DB slice](tasks/P03-T01c.md) follows the [proposal](tasks/P03-T01c-design.md) under the owner’s later broad step-by-step permission. PostgreSQL migration/legacy mismatch/insert/update tests passed [CI run 38863934464](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38863934464). Registration/credentials/sessions remain unimplemented and need separate staged security review.
- **P03-T01d (complete 2026-10-16):** [Fixed V1 player username database guard](tasks/P03-T01d.md) blocks update/reassignment/deletion of assigned player login names. PostgreSQL trigger behavior and migration round-trip passed [CI run 38864125620](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38864125620); D-02 deletion/reuse remains open.
- **P03-T01e (complete 2026-10-16):** [Fixed V1 Agent-ID database guard](tasks/P03-T01e.md) follows approved [D-12](decisions/2026-10-16-owner-bootstrap-and-agent-id-lifecycle.md). PostgreSQL trigger/round-trip tests passed [CI run 38865633220](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38865633220); owner bootstrap security/credential/MFA flow is future work.
- **P03-T01f (complete 2026-10-16):** [Pure cryptographic helpers](tasks/P03-T01f.md) for Argon2id passwords and high-entropy one-time secret digests; no credential persistence or auth endpoint. Python 3.12 CI passed [CI run 38865947836](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38865947836); credential persistence/activation still need security review.
- **P03-T01g (complete 2026-10-16):** [D-13 password policy guard](tasks/P03-T01g.md) validates new permanent passwords before Argon2id hashing; [CI run 38866281196](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38866281196) passed, no endpoints.
- **P03-T01h (complete 2026-10-16):** [Credential-state schema](tasks/P03-T01h.md) stores only hashed initial secrets/passwords with structural pending/active checks and a one-way guard. **Gate:** PostgreSQL migration/constraint tests passed [CI run 38866772047](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38866772047). No issuance/activation/auth service yet.
- **P03-T01i (complete 2026-10-16):** [Security-event journal](tasks/P03-T01i.md) adds a minimal append-only audit foundation with PostgreSQL integrity tests; [CI run 38867010258](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38867010258) passed. No service writes it yet.
- **D-14 (approved 2026-10-16):** [Single-owner fixed `owner` login label](decisions/2026-10-16-owner-login-identifier.md) remains public and is resolved by unique OWNER role; password/MFA/session enforcement still required.
- **P03-T01j (complete 2026-10-16):** [Pure owner MFA primitives](tasks/P03-T01j.md) cover RFC 6238 TOTP and high-entropy recovery codes; no encryption/storage/enrollment/session. **Gate:** Python 3.12 [CI run 38867519974](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38867519974) passed; separate key-management review still required.
- **P03-T01k (complete 2026-10-16):** [Owner-bound TOTP encryption primitive](tasks/P03-T01k.md) uses D-15 external key custody direction; [CI run 38867838880](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38867838880) passed. No seed persistence or key loader.
- **P03-T01l (complete 2026-10-16):** [Owner MFA storage schema](tasks/P03-T01l.md) holds owner-bound encrypted factor data and one-time hashed recovery-code rows. **Gate:** PostgreSQL migration/integrity tests passed [CI run 38868491900](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38868491900); no enrollment/session service.
- **P03-T01m (complete 2026-10-19):** [Restricted owner MFA key loader](tasks/P03-T01m.md) reads only versioned keys from a secure deployment file. **Gate:** Python 3.12 [CI run 39202950085](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/39202950085) passed; no enrollment or key rotation.
- **P03-T01n (complete 2026-10-19):** [Internal audited owner bootstrap/reissue](tasks/P03-T01n.md) writes OWNER, pending digest and audit in one caller transaction. **Gate:** PostgreSQL rollback/disabled/activated tests passed [CI run 39203138653](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/39203138653); no CLI or owner access.
- **P03-T01o (complete 2026-10-19):** [Internal initial owner activation](tasks/P03-T01o.md) verifies token/DB-clock expiry, sets Argon2id password and audit atomically. **Gate:** PostgreSQL replay/expiry/rollback tests passed [CI run 39203336370](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/39203336370); no route/session/MFA grant.
- **P03-T01p (complete 2026-10-19):** [Internal owner MFA enrollment](tasks/P03-T01p.md) stores encrypted factor, confirms with live TOTP and ten hashed codes/audit. **Gate:** PostgreSQL rollback/replay tests passed [CI run 39203550214](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/39203550214); no UI/session.
- **P03-T01q (complete 2026-10-19):** [Local owner setup CLI](tasks/P03-T01q.md) exposes only terminal-based dev bootstrap/activation/MFA setup. **Gate:** TTY/commit-order/error tests passed [CI run 39204219810](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/39204219810); no owner session or production adapter.
- **P03-T02a (complete 2026-10-19; [CI 39204471202](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/39204471202)):** [Session schema](tasks/P03-T02a.md) constrains D-03 role-specific idle/absolute deadlines, one unrevoked session per account, and owner MFA timestamp presence; **no login/session issuance exists**. **Gate:** migration round-trip, DB constraint tests, Ruff and full suite in CI.
- **P03-T02 (remaining):** Login/logout, secure cookies, DB-time session validation, new-login/disablement invalidation, reconnect/forced logout. **Gate:** session replay/stale-session tests on API and realtime connections.
- **P03-T03:** Owner TOTP/recovery-code MFA and D-03-approved session/step-up policy; rate limits and audit. Manual all-factors-lost recovery is not approved and must not be improvised. **Gate:** MFA required for privileged access and tested failure/recovery paths before production.

### P04 — Resource-level authorization

- **P04-T01:** Define server-side role/action/resource matrix for owner, agent, and player; enumerate data each may read/write. **Gate:** owner-reviewed policy and threat cases.
- **P04-T02:** Enforce checks at API and data access boundaries; never trust client-supplied player/agent IDs as authorization. **Gate:** cross-agent and cross-player ID tampering tests, including disabled accounts.
- **P04-T03:** Protect realtime private subscriptions and audit privileged actions. **Gate:** another player's bets, balance, and history never appear in API or WebSocket payloads.

### P05 — Wallet and point ledger

- **P05-T01:** Define immutable ledger types for explicit owner issuance, paired owner/agent/player transfers, game reserve funding/stakes/payouts/refunds; wallet invariants, gameplay-vs-admin P/L, reference IDs and reconciliation. **Gate:** transfer conservation, owner-only issuance, approved total-return convention and negative-balance/duplicate-entry constraints reviewed; do not code unapproved POOL-01 global reserve restriction.
- **P05-T02:** Implement atomic, idempotent owner issuance and funded wallet transfers with actor, source, target, reason and audit context; player starts at zero. **Gate:** concurrent transfers cannot double-spend source wallets, create points or partially move an unaffordable request; failure rolls back both sides.
- **P05-T03:** Reconciliation, correction policy, and backup/restore accounting checks. **Gate:** wallet totals reconcile to ledger in seeded integration scenarios; no silent balance edits.

### P06 — Owner/admin operations

- **P06-T01:** Scope owner API: provision/manage agents and users, disable/enable, point actions (D-01 required for removal). **Gate:** every privileged route enforces MFA/role, reason, audit, and budget rules.
- **P06-T02:** Build admin UI for those APIs with confirmation/error states, reports and audit review. **Gate:** functional and accessibility tests; aggregate gameplay P/L remains distinct from admin adjustments.

### P07 — Agent operations

- **P07-T01:** Scope agent API to assigned users and allocations. **Gate:** agents cannot enumerate/change another agent's users or exceed allocated budget under concurrent requests.
- **P07-T02:** Build agent UI and history views within authorized scope. **Gate:** cross-agent and stale-session E2E tests plus accessible failure handling.

### P08 — Authoritative roulette engine

- **P08-T01:** Translate catalogue fixture and approved multipliers into runtime validation/payout pure functions; protect bet-type distinctions, zero handling, normalization. **Gate:** fixture and payout table cases, including 10 straight-up → 350 total, pass; no API acceptance yet.
- **P08-T02:** Implement persisted global 60-second round state machine, server cutoff/freeze at second 50, one independently generated outcome, reveal at second 60, worker ownership/recovery design (D-06). **Gate:** deterministic clock/failure-injection tests show one result, no post-cutoff acceptance, and no client-driven outcome.
- **P08-T03:** Transactional settlement and terminal `SETTLED` vs `VOID_REFUNDED` recovery. **Gate:** real PostgreSQL retry/race tests prove no double payout, refund, or outcome regeneration; retain persisted outcome for audit.

### P09 — Realtime delivery

- **P09-T01:** Version and implement public round event contract (phase, countdown, result/history) and authenticated private player updates; decide replay/sequence (D-08). **Gate:** public payloads contain no private bets/balances.
- **P09-T02:** Reconnect/snapshot flow and load-aware fan-out; Redis only with an explicit role. **Gate:** reconnect sees server state, stale sessions cannot subscribe, missed events do not rewrite accepted bets.

### P10 — Player experience

- **P10-T01:** Original visual system, responsive table/wheel placeholders, login, round state, balance and current-session history against authorized contracts. **Gate:** desktop and mobile landscape layouts have usable controls and no leaked private data.
- **P10-T02:** Connect authoritative round/reconnect states and clear pending/error/void feedback. **Gate:** E2E navigation, disconnect, empty balance, and result display tests.

### P11 — Betting controls and acceptance

- **P11-T01 (server):** Implement acceptance with full-balance check, valid stake/chips, canonical position, cutoff, per-number straight/split exposure, exact-selection caps, duplicate records, and atomic cap-limited partial acceptance. Separately approve POOL-01 funding/coverage and any global acceptance restriction before adding it. **Gate:** PA-01–PA-18, PA-20–PA-21, funded-reserve invariant (once approved) and relevant PostgreSQL concurrent requests; no balance-limited partial bet.
- **P11-T02 (server):** Implement player-specific all-or-nothing rebet with idempotency. **Gate:** PA-19, duplicate retry, cutoff and concurrent wallet/cap tests.
- **P11-T03 (client):** Draft chip placement/edit/cancel before submission, pending/confirmed distinction, immutable accepted bets, combined duplicate display and rebet UX. **Gate:** E2E insufficient balance, cap return, cutoff, retries, and disconnect behavior; no optimistic bet treated as accepted.
- **P11-T04 (cross-service):** Wire bet results into P08 settlement and P09 private events. **Gate:** PA-22/PA-23 and player privacy end-to-end on a shared round. P00-T02 cannot be marked verified before these gates pass.

### P12 — Wheel animation

- **P12-T01:** Design an original, realistic-feeling single-zero European wheel: review authentic pocket order, proportions and visuals against D-09; wheel and ball spin smoothly with believable counter-motion, deceleration and final landing. The persisted server result and authoritative timing drive the landing; simulated physics, animation randomness and the client must never compute or change the winning number. **Gate:** recorded-result landing matches the announced pocket across refresh/reconnect and supported devices, no jarring jumps at phase boundaries, reduced-motion alternative preserves result clarity, and measured smoothness/performance meets an owner-approved device budget. Verify visual realism with owner review; do not claim real-world physics accuracy without validation.

### P13 — Audio and settings

- **P13-T01:** Wheel/ball/chip/button/result effects only; separate volume controls, mute/reduced-stimulation behavior, decide settings persistence. **Gate:** settings and accessibility tests, no background music/ambience, asset licensing reviewed.

### P14 — UI quality and responsiveness

- **P14-T01:** Audit desktop and dedicated mobile landscape layout, safe areas, resize/rotation, keyboard/focus and contrast. **Gate:** defined viewport/device matrix, no clipped/unusable controls, recorded accessibility findings and fixes.
- **P14-T02:** Review admin/agent/player usability, errors and loading states against original design/reference guidance. **Gate:** regression E2E and owner UX approval.

### P15 — Reliability hardening

- **P15-T01:** End-to-end failure matrix: dropped connections, clock drift, cutoff races, retried requests, database/worker restarts and outage/restore. **Gate:** accepted bets survive player disconnect; accounting ends in exactly one terminal state.
- **P15-T02:** Document incident handling, alarms, recovery worker limits and operator runbooks. **Gate:** repeatable drill with audit trail and no manual wallet patching.

### P16 — Security and full test gate

- **P16-T01:** Consolidate unit, PostgreSQL integration/concurrency, contract and browser E2E suites in CI; run supported-version checks and failure injection. **Gate:** failures block merges and test evidence is recorded.
- **P16-T02:** Threat model/authz review (including WebSockets), dependency/secrets review, OWASP ASVS baseline, privacy checks and accessibility regression. **Gate:** critical findings fixed or explicitly blocked; do not claim certification.

### P17 — Performance

- **P17-T01:** Approve D-04 numbers and representative player/bet/device workload. **Gate:** measurable targets, environment and pass/fail method recorded before load runs.
- **P17-T02:** Load-test round transitions, betting/cap contention, realtime fan-out, settlement and reconnect; tune without weakening accounting. **Gate:** agreed targets met with repeatable results or stage remains open.

### P18 — Staging and owner acceptance

- **P18-T01:** Staging deployment using non-production/seeded data, TLS/config/secrets, monitoring, migration and documented rollback. **Gate:** backup/restore and rollback rehearsal recorded.
- **P18-T02:** Owner acceptance of a full virtual-points round, admin→agent→player flows, landscape UX, failure recovery and disclosures; resolve D-05. **Gate:** signed-off acceptance and open-issue disposition.

### P19 — Production launch

- **P19-T01:** Launch checklist: security and legal/privacy review, MFA, monitoring/on-call, capacity, backup/restore, rollback, operations ownership and explicit owner go/no-go. **Gate:** all release criteria evidenced; otherwise do not launch.
- **P19-T02:** Controlled release and post-launch verification of health, accounting reconciliation, alerts and incident response. **Gate:** launch report and rollback decision documented.

## First small next step (requires owner permission)

The owner approved this delivery sequence on 2026-10-15. Next, seek separate permission to verify **P01-T01 only** in a supported Python environment. No betting-engine, UI, database, or gameplay implementation is included in that verification task. A reference game is optional for later visual review, not a blocker now.
