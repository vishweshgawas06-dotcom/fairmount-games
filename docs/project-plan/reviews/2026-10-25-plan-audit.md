# Project plan audit — 2026-10-25

## Scope and method

Audited the current plan, requirements, payout rules, cap matrix, betting architecture, conceptual transaction design, P00-T02, status and next-action documents against owner decisions D-06a and POOL-01 and the task/CI record. Searched the project-plan Markdown line by line for contradictory recovery, implementation and authorization claims, then manually reconciled the active specification and current-facing statements. A local-link test scans **every** Markdown file under `docs/project-plan` for missing local targets (file existence, not fragment validity or external availability). Historical dated task records were not retroactively rewritten simply because their checkpoints predate newer slices.

## Verified corrections

| Finding | Resolution |
|---|---|
| 2026-10-14 automatic settlement-failure void/refund text still appeared as active policy in P00-T02, the payout spec, architecture, cap matrix and conceptual transactions; a persisted outcome was even described as voidable. | Marked original approval as historical and superseded by [D-06a](../decisions/2026-10-24-round-result-recovery.md). Missing result: independently select/persist once after cutoff and settle late. Persisted result: reuse and retry settlement; never reroll, automatically void or refund it. Exceptional pre-result incident void is a separate unapproved audited policy. POOL-01 full-void-refund *coverage* remains required even though void is not the routine recovery path. |
| Cap matrix said split acceptance was limited by a `split-selection cap` despite explicitly stating no such exact-split cap exists. | Removed that phantom cap from the algorithm; the 2,000-point per-number exposure applies to each constituent number. |
| MASTER_PLAN still demanded permission for each task after the owner granted broad step-by-step authorization. | Updated permission language; consequential unresolved product/security decisions still require explicit input. |
| Core requirements, delivery plan, conceptual design and status called private auth, POOL-01, cap/admission or payout wholly unimplemented; P01-T01 was described as unverified and P02 follow-ups unauthorized. | Distinguished tested **private/opt-in direct-TLS** slices from absent public write/gameplay, proxy deployment and production acceptance. Preserved earlier checkpoints as historical rather than silently treating them as current. |
| Status/next action could be read as though P04-T02b or HTTP login were still the next unimplemented feature. | Added a compact current-evidence summary and explicit next gates. Existing checkpoint CI references remain in task records/delivery plan. |

## Verification

- Baseline before edits: Ruff passed; `unittest discover -s tests -q` ran 215 tests with 136 local DB skips and no failures; 95 pure roulette pytest cases and three Node wheel tests passed. This is Python 3.11 local evidence, **not** a PostgreSQL run.
- After edits: 113 project-plan Markdown files and 321 local file references checked by new link/supersession tests; **zero missing local targets**. Ruff passed; `unittest discover -s tests -q` ran **217 tests, 136 DB-gated skips, 0 failures**; pure roulette pytest **95 passed**; Node wheel tests **3 passed**; `git diff --check` passed. The first run caught the as-yet-unwritten audit-report link and Ruff import ordering/trailing whitespace; the report was written and formatting fixed, then all checks passed.
- The audit commit `cc33105` passed [Python 3.12/PostgreSQL CI 40195121369](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/40195121369): migration round-trip, DB-enabled unittest, pure pytest, Node wheel tests and Ruff. Prior [P04-T02i CI 40192708908](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/40192708908) and [evidence CI 40192800198](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/40192800198) also passed. CI emitted non-failing GitHub Actions Node 20/Ubuntu image migration advisories for later maintenance.

## Still open; do not infer a playable product

1. Full request-edge gameplay writes, authorized funding/account writes, cross-account/realtime bet privacy and production proxy/TLS deployment. Keep opt-in private routes disabled in the HTTP preview.
2. Supervised D-06a worker retries, operator alerts/backoff, delayed-result UI, failure-injection/latency targets and an independently approved exceptional incident-void policy. A worker crash is not a void trigger.
3. D-02 retention/deletion/backups, all-factors-lost owner recovery procedure, performance/SLO targets and payout-wording UX review (approved total-return multipliers differ from conventional casino total return).
4. PR #1 remains `OPEN`/`CONFLICTING` with main's integer-ID engine core at audit time. Passing branch CI does not demonstrate a mergeable combined tree; do not import incompatible schema by implication.
5. This audit validates plan consistency and local file links, not Markdown anchor resolution, external links, all historical statements at today's date, database behavior in this sandbox, production load, accessibility or browser/device appearance.
