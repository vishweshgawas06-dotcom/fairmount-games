# Next Action

## Active task

**P00-T02 — Approve roulette bet types and payout rules.**

## Objective

Review and approve the complete V1 bet catalogue and settlement rules before implementing the betting engine.

## Current draft

See [Roulette Payout and Settlement Specification (Draft)](roulette/PAYOUT_AND_SETTLEMENT_SPEC_DRAFT.md). It is a proposal and is not approved yet.

## Requirements recorded for review

- Original payout ratios remain unchanged, but the multiplier calculates **total payout including the placed stake**. Example: a 10-coin straight-up win credits 350 coins total, not 360.
- Each player has an individual roulette table view and sees only their own bets and amounts. Other players' individual bets and amounts remain private. The winning result is global and shared.
- Maximum stake is 2,000 coins per individual selection, not a total-round cap. This applies to all bet types; the previous proposed 3,000-coin cap for other bet categories is superseded.
- REBET copies that player's own previous-round bet set and amounts. The complete set is accepted only if the available balance covers its total stake; otherwise none is placed. After acceptance, the player can add/remove/change bets while betting remains open.
- At second 45, show the final-bet call. At second 50, close/freeze bets and start the wheel/ball spin. At second 60, reveal the result and credit the player's aggregate winning payout.
- One server-authoritative result is shared by all players; result generation is independent of bets and balances. Settlement must be transactional and idempotent.

## Remaining decisions before approval

- Minimum stake and exact chip-increment rule.
- Duplicate bets on the same selection and how they are represented.
- Exact stake-edit semantics after acceptance.
- Void-round/refund policy.
- Final approved mapping of valid inside-bet positions.
- Explicit product-owner approval of the complete proposal.

## Do not do yet

Do not implement payout code or silently choose missing bet rules. Record open questions and ask for approval.
