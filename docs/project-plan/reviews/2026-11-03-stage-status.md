# Stage status scan — 2026-11-03

A line-by-line pass over the [delivery plan](../DETAILED_DELIVERY_PLAN.md),
task records and current code, to state **what is finished, what is partly
finished and what has not started**. Checkpoint CI links live in the task
records; this page summarises scope, not new evidence. "Done" means the planned
private/opt-in slice is implemented and tested — never that a public, deployed
product exists.

## Matrix

| Phase | State | Implemented and tested | Not done |
|---|---|---|---|
| **P00** Specification lock | **Done** | `P00-T02` payout/settlement spec, `T03`/`T04` acceptance docs; superseded recovery text reconciled by the [2026-10-25 audit](2026-10-25-plan-audit.md) and D-06a. | Owner wording/UX review of total-return multipliers. |
| **P01** Repository foundation | **Done** | Tooling, health endpoint, local PostgreSQL foundation (`T01`–`T03`). | — |
| **P02** Database and migrations | **Done** | Account/identity/credential/session/MFA/ledger/round/bet/auth-attempt schemas, roster index, and `20261103_01` write-window schema; round-trip + `alembic check` in CI. | Physical BIGINT-vs-UUID reconciliation with `main`/PR #1; D-02 retention/backups. |
| **P03** Authentication and sessions | **Done (opt-in)** | Identifier rules, password policy, Argon2id, TOTP/recovery codes, key custody, owner bootstrap/activation/MFA, sessions, logout, rate limiting, CSRF boundary (`T01a`–`T02p`). | Provisioning/registration endpoints, all-factors-lost recovery, trusted reverse-proxy policy, production MFA key rotation. |
| **P04** Resource authorization | **Done (opt-in)** | Self wallet/recent bets, scoped player wallet, live ID-only roster, bounded keyset pages, owner/agent real-HTTP flows (`T01a`–`T02i`). | Cross-account bet history, realtime authorization, operator-authorized assignment writes over HTTP. |
| **P05** Wallet and point ledger | **Done (private)** | UUID ledger, paired append-only journal, issuance, owner/agent transfers, reserve funding/withdrawal, reconciliation (`T01a`–`T03a`). | Request-edge transfer routes, retention policy for the journal. |
| **P06** Owner/admin operations | **Not started** | Only private services the future UI would call. | Owner API scope, provisioning/assignment write endpoints, admin UI. |
| **P07** Agent operations | **Not started** | Private assigned-player transfer and roster reads. | Agent API write routes, agent UI, history views. |
| **P08** Roulette engine | **Done (private)** | Catalogue/payout/cap rules, round/open-close, once-only independent result, D-06a recovery, due-round worker, singleton poller (`T01`–`T02d`). | Supervised deployment, alerting, failure-injection matrix. |
| **P09** Realtime delivery | **Partial** | Public read-only snapshot (`T01a`/`T01b`) and a reveal-only server-sent event stream with de-duplication, heartbeats and a per-process connection cap (`T02a`). | Private/authenticated realtime channel, bet-lock/bet-accepted events, reconnect/replay contract (D-08), realtime session revocation. |
| **P10** Player experience | **Partial** | Read-only preview UI with server-aligned wheel (`T01a`). | Real client, betting UI, wallet/history screens, delayed-result UX. |
| **P11** Betting controls | **Done (opt-in)** | Admission, caps, POOL-01 coverage, settlement, rebet, idempotent HTTP write route (`T01a`–`T03a`), attempt windows (`T03b`). | Bet UI, per-player (not per-session) budgets, staging acceptance. |
| **P12** Wheel animation | **Not started** | Preview-only static wheel alignment. | Production animation, timing budgets, reduced-motion variants. |
| **P13** Audio and settings | **Not started** | — | Sound design, mute/volume persistence, accessibility settings. |
| **P14** UI quality | **Not started** | Preview layout only. | Desktop/device audits, admin/agent/player consistency review. |
| **P15** Reliability hardening | **Partial** | Due-round inventory CLI, schema readiness (`T02a`/`T02b`). | End-to-end failure matrix, incident runbook, supervised restart procedure. |
| **P16** Security/test gate | **Partial** | Per-slice security tests, CSRF/cookie boundary, pseudonymous throttling. | Consolidated threat model, full security review sign-off. |
| **P17** Performance | **Not started** | Bounded queries exist. | Approved SLO/latency targets, load tests, capacity evidence. |
| **P18** Staging and acceptance | **Not started** | — | Staging deployment, owner acceptance of a full round. |
| **P19** Production launch | **Not started** | — | Launch checklist, controlled release, post-launch monitoring. |

## Reading the matrix

- **P00–P05, P08 and P11 are complete as *private or opt-in* slices.** Nothing
  they implement is reachable by an ordinary player in the preview deployment.
- **P06, P07, P12–P14, P17–P19 have not started.** The product cannot be called
  playable until at least P06/P07 (operations), P09-T02 (realtime), P10-T02 (bet
  UI) and P17 (targets) progress.
- **P09, P10, P15 and P16 are partly done** and each has a clearly bounded next
  step.
- Two items block *any* deployment regardless of phase: the trusted
  reverse-proxy/client-IP decision and PR #1's conflict with `main`.

## Next bounded step taken with this scan

[P11-T03b](../tasks/P11-T03b.md) closed the abuse gap opened by the first write
route: gameplay writes now take pseudonymous session (20/min) and source
(120/min) attempt windows inside the admission transaction, so a valid session
cannot flood the reserve path. It is the prerequisite for exposing any bet
endpoint beyond a lab.
