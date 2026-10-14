# Project Status

**Current phase:** P00 — Specification lock  
**Current task:** P00-T02 — Approve roulette bet types and payout rules  
**Implementation status:** Not started / not verified  
**Specification status:** Payout/settlement specification and canonical legal-position catalogue approved by owner on 2026-10-14; automated cap/partial-acceptance and catalogue-fixture verification pending  
**Last updated:** 2026-10-14

## Completed in repository

- Initial repository baseline and development/security guidance.
- Master phase plan and immediate next-task definition.
- Updated the P00-T02 draft to record total-payout multipliers, player-private bet data, per-number straight-up/split exposure caps, all confirmed per-selection caps, chip denominations, duplicate records, local-draft editing, immutable accepted bets, rebet rules, round timing, player-disconnect behavior, owner-selected atomic settlement/refund recovery, and standard European layout.
- Recorded the owner's four choices dated 2026-10-14 in the draft, P00-T02 task, and NEXT_ACTION.md.
- Recorded the owner's explicit approval of the P00-T02 payout/settlement specification on 2026-10-14.
- Owner approved the canonical legal-position catalogue on 2026-10-14; catalogue counts and red/black test fixtures still require automated verification.
- Added `docs/project-plan/roulette/CAP_PARTIAL_ACCEPTANCE_EDGE_CASES.md` to define required cap, partial-acceptance, concurrency, rollback, and idempotency checks; not yet implementation/test evidence.

## Blocking specification decisions

- Verify cap/partial-acceptance behavior against `roulette/CAP_PARTIAL_ACCEPTANCE_EDGE_CASES.md`, including concurrent requests, rollback, and idempotency.
- Encode and verify catalogue counts and fixed red/black sets in deterministic tests before betting-engine implementation.
- Owner decision recorded: reject ordinary bets in full if balance cannot cover the requested stake; cap-limited partial acceptance remains permitted when the full request is affordable.
- User/agent removal and point-accounting behavior.
- Historical record retention, anonymization, and deletion policy.
- Owner MFA recovery and session policy.
- Measurable performance/availability targets and acceptance thresholds.

## Important status distinction

The owner approved the payout/settlement specification and canonical legal-position catalogue on 2026-10-14. Edge-case policy and acceptance-criteria verification remain open. No betting-engine implementation or production behavior has been verified. Do not mark P00-T02 complete until these remaining gates are verified.

## Status update rule

After each completed task, update this file and NEXT_ACTION.md. Mark a task complete only when its acceptance criteria and verification evidence are recorded. Never infer success from code generation alone.
