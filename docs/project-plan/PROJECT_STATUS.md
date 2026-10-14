# Project Status

**Current phase:** P00 — Specification lock  
**Current task:** P00-T02 — Verify catalogue fixture and cap/partial-acceptance criteria  
**Implementation status:** Betting engine not started  
**Specification status:** Payout/settlement specification and canonical legal-position catalogue approved by owner on 2026-10-14  
**Verification status:** Deterministic catalogue fixture and Python tests committed; test execution and cap-matrix review pending  
**Last updated:** 2026-10-14

## Completed in repository

- Initial repository baseline and development/security guidance.
- Master phase plan and immediate next-task definition.
- P00-T02 payout/settlement specification records total-payout multipliers, player-private bet data, per-number straight-up/split exposure caps, all confirmed per-selection caps, chip denominations, duplicate records, local-draft editing, immutable accepted bets, rebet rules, round timing, player-disconnect behavior, owner-selected atomic settlement/refund recovery, and standard European layout.
- Owner's specification choices and approval recorded on 2026-10-14.
- Owner-approved canonical legal-position catalogue with fixed red/black sets and expected counts.
- Cap/partial-acceptance edge-case matrix covering acceptance, exposure caps, concurrency, cutoff, normalization, idempotency, rollback, rebet, insufficient balance, and settlement/refund.
- Added deterministic JSON fixture tests/fixtures/roulette_catalogue.json, including all canonical inside selections, outside sets, red/black sets, and expected catalogue counts.
- Added standard-library test suite tests/test_roulette_catalogue_fixture.py to compare fixture data with independently generated expected combinations and validate catalogue counts/color coverage.

## Current verification gates

- Execute python -m unittest discover -s tests -v and record actual results; committed test files are not proof that the tests have passed.
- Review PA-01 through PA-23 against locked requirements and define the automated verification plan for caps, balance reservation, concurrency, rollback, idempotency, settlement, and void/refund.
- Ensure future API/realtime authorization tests prove player-private bet data cannot be read by other players.
- Resolve remaining non-blocking product/operations decisions: user/agent removal and point-accounting behavior; historical record retention/anonymization/deletion; owner MFA recovery/session policy; measurable performance/availability targets.

## Important status distinction

The owner approved the payout/settlement specification and canonical legal-position catalogue on 2026-10-14. Catalogue fixture and test artifacts now exist, but test execution and cap/partial-acceptance verification remain open. No betting-engine implementation or production behavior has been verified. Do not mark P00-T02 complete until the remaining gates and acceptance criteria have recorded evidence.

## Status update rule

After each completed task, update this file and NEXT_ACTION.md. Mark a task complete only when its acceptance criteria and verification evidence are recorded. Never infer success from code generation alone.
