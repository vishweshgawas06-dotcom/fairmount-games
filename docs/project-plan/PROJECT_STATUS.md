# Project Status

**Current phase:** P00 — Specification lock  
**Current task:** P00-T02 — Approve roulette bet types and payout rules  
**Implementation status:** Not started / not verified  
**Specification status:** Revised draft documented; product-owner approval pending  
**Last updated:** 2026-10-13

## Completed in repository

- Initial repository baseline and development/security guidance.
- Master phase plan and immediate next-task definition.
- Updated the P00-T02 draft to record total-payout multipliers, per-player bet privacy, 2,000-coin per-selection cap, individual previous-bet rebet behavior, and second-45/50/60 round timing.

## Blocking specification decisions

- Product-owner approval of the full roulette bet catalogue and payout convention.
- Minimum stake/chip increment and duplicate-selection behavior.
- Exact stake-edit semantics after acceptance.
- Void-round and refund policy.
- Final valid table-layout mapping for all supported inside bets.
- User/agent removal and point-accounting behavior.
- Historical record retention, anonymization, and deletion policy.
- Owner MFA recovery and session policy.
- Measurable performance/availability targets and acceptance thresholds.

## Important status distinction

The roulette payout/settlement document is a draft, not an approved requirement. No betting engine implementation or production behavior has been verified. Do not mark P00-T02 complete until approval and acceptance evidence are recorded.

## Status update rule

After each completed task, update this file and NEXT_ACTION.md. Mark a task complete only when its acceptance criteria and verification evidence are recorded. Never infer success from code generation alone.
