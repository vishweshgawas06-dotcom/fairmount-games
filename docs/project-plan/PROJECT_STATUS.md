# Project Status

**Current phase:** P00 — Specification lock  
**Current task:** P00-T02 — Approve roulette bet types and payout rules  
**Implementation status:** Not started / not verified  
**Specification status:** P00-T02 payout/settlement specification approved by owner on 2026-10-14; canonical position catalogue review pending  
**Last updated:** 2026-10-14

## Completed in repository

- Initial repository baseline and development/security guidance.
- Master phase plan and immediate next-task definition.
- Updated the P00-T02 draft to record total-payout multipliers, player-private bet data, per-number straight-up/split exposure caps, all confirmed per-selection caps, chip denominations, duplicate records, local-draft editing, immutable accepted bets, rebet rules, round timing, player-disconnect behavior, owner-selected atomic settlement/refund recovery, and standard European layout.
- Recorded the owner's four choices dated 2026-10-14 in the draft, P00-T02 task, and NEXT_ACTION.md.
- Recorded the owner's explicit approval of the P00-T02 payout/settlement specification on 2026-10-14. The next gate is review of the canonical legal-position catalogue.

## Blocking specification decisions

- Review the canonical valid European table-position catalogue, especially zero-adjacent combinations.
- Confirm partial acceptance and immediate excess refund behavior for every applicable cap, including split bets, against the selected chip/minimum rules.
- Complete and review the canonical valid European table-position catalogue, especially zero-adjacent combinations, before betting-engine implementation.
- Verify partial-acceptance and immediate excess-refund behavior for every applicable cap, including split bets, against chip/minimum rules.
- User/agent removal and point-accounting behavior.
- Historical record retention, anonymization, and deletion policy.
- Owner MFA recovery and session policy.
- Measurable performance/availability targets and acceptance thresholds.

## Important status distinction

The owner approved the P00-T02 payout/settlement specification on 2026-10-14, and the approval is recorded in the task and specification. The legal-position catalogue and acceptance-criteria verification remain open. No betting-engine implementation or production behavior has been verified. Do not mark P00-T02 complete until these remaining gates are verified.

## Status update rule

After each completed task, update this file and NEXT_ACTION.md. Mark a task complete only when its acceptance criteria and verification evidence are recorded. Never infer success from code generation alone.
