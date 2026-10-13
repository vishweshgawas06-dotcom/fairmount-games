# Project Status

**Current phase:** P00 — Specification lock  
**Current task:** P00-T02 — Approve roulette bet types and payout rules  
**Implementation status:** Not started / not verified  
**Specification status:** Owner choices recorded; full-spec approval pending  
**Last updated:** 2026-10-13

## Completed in repository

- Initial repository baseline and development/security guidance.
- Master phase plan and immediate next-task definition.
- Updated the P00-T02 draft to record total-payout multipliers, per-player bet privacy, 2,000-coin per-selection cap, individual previous-bet rebet behavior, second-45/50/60 round timing, and the owner's latest chip, duplicate-record, atomic-edit, void-review, and standard-layout choices.
- Updated P00-T02 and NEXT_ACTION.md with remaining ambiguities and explicit no-implementation/no-approval gates.

## Blocking specification decisions

- Resolve the duplicate-selection interaction with the 2,000-coin cap.
- Define the scope of a multi-selection atomic edit.
- Define owner/admin decisions and timing for frozen/void rounds, including refund/resume behavior.
- Publish exact valid European table-position mappings for all supported inside bets, especially zero-adjacent positions and first four.
- Define failure recovery before/after outcome persistence and result display.
- Product-owner approval of the complete roulette bet catalogue and payout convention.
- User/agent removal and point-accounting behavior.
- Historical record retention, anonymization, and deletion policy.
- Owner MFA recovery and session policy.
- Measurable performance/availability targets and acceptance thresholds.

## Important status distinction

The roulette payout/settlement document is a draft, not an approved requirement. The owner's five latest choices have been recorded but do not approve the complete specification. No betting-engine implementation or production behavior has been verified. Do not mark P00-T02 complete until remaining ambiguities are resolved, full approval is explicitly given, and acceptance evidence is recorded.

## Status update rule

After each completed task, update this file and NEXT_ACTION.md. Mark a task complete only when its acceptance criteria and verification evidence are recorded. Never infer success from code generation alone.
