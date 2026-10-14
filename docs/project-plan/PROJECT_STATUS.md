# Project Status

**Current phase:** P00 — Specification lock  
**Current task:** P00-T02 — Approve roulette bet types and payout rules  
**Implementation status:** Not started / not verified  
**Specification status:** Latest owner rules recorded; full-spec approval pending  
**Last updated:** 2026-10-14

## Completed in repository

- Initial repository baseline and development/security guidance.
- Master phase plan and immediate next-task definition.
- Updated the P00-T02 draft to record total-payout multipliers, player-private bet data, per-number straight-up/split exposure caps, outside-selection caps, chip denominations, duplicate records, immutable accepted bets, rebet rules, round timing, player-disconnect behavior, server/game-side failure refunds, and standard European layout.
- Updated P00-T02 and NEXT_ACTION.md with remaining interpretations and explicit approval/implementation gates.

## Blocking specification decisions

- Confirm cap treatment for corner, six-line, first-four, and Low/High selections.
- Confirm “rows” means street/row bets.
- Confirm partial acceptance and immediate excess refund behavior, including split bets.
- Confirm pre-acceptance edit/cancel interaction.
- Review the canonical valid European table-position catalogue.
- Confirm the recommended server/game-side failure recovery rules.
- Obtain product-owner approval of the complete roulette specification.
- User/agent removal and point-accounting behavior.
- Historical record retention, anonymization, and deletion policy.
- Owner MFA recovery and session policy.
- Measurable performance/availability targets and acceptance thresholds.

## Important status distinction

The roulette payout/settlement document is a draft, not an approved requirement. The latest owner rules and a labelled recovery recommendation have been recorded, but the complete specification is not approved. No betting-engine implementation or production behavior has been verified. Do not mark P00-T02 complete until remaining decisions are resolved, full approval is explicit, and acceptance evidence is recorded.

## Status update rule

After each completed task, update this file and NEXT_ACTION.md. Mark a task complete only when its acceptance criteria and verification evidence are recorded. Never infer success from code generation alone.
