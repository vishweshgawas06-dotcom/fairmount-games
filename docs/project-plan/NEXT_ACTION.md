# Next Action

## Active task

**P00-T02 — Approve roulette bet types and payout rules.**

## Objective

Resolve remaining ambiguities and obtain explicit approval of the complete V1 bet catalogue and settlement rules before implementing the betting engine.

## Current draft

See [Roulette Payout and Settlement Specification (Draft)](roulette/PAYOUT_AND_SETTLEMENT_SPEC_DRAFT.md). It records the owner's latest choices but remains a proposal and is not approved.

## Owner choices recorded for review

- Original payout ratios calculate **total payout including the placed stake**. Example: a 10-coin straight-up win credits 350 coins total, not 360.
- Each player has an individual roulette table view and sees only their own bets and amounts. Other players' individual bets remain private; the winning result is global and shared.
- Maximum stake is 2,000 coins per individual bet selection, not a total-round cap; this applies to all bet types.
- REBET copies that player's own previous-round bet set and amounts. The complete set is accepted only if the available balance covers its total stake; otherwise none is placed.
- Seconds 0–44 betting open; second 45 final-bet call; second 50 close/freeze bets and start animation; second 60 reveal result and credit aggregate winning payout.
- One server-authoritative result is shared by all players; result generation is independent of bets and balances. Settlement must be transactional and idempotent.
- Minimum stake 5; allowed chip denominations 5, 10, 50, 100, 500.
- Duplicate identical selections remain separate records, but the UI displays their combined stake clearly.
- Bet edits are atomic: validate the full requested change first, then accept all or leave the prior accepted state unchanged.
- A round that cannot safely complete freezes settlement for owner/admin review.
- Standard European layout only; only valid standard selections are allowed.

## Remaining decisions before approval

1. Does the 2,000-coin cap apply to combined duplicate records for the same exact selection or separately to each record?
2. Is an edit affecting multiple selections one all-or-nothing operation, or is each selection edited independently?
3. What actions can owner/admin take for a frozen round (including refund versus resuming settlement with the persisted outcome), and what happens if review is delayed?
4. Record the exact valid-position catalogue for zero-adjacent inside bets and first four.
5. Define failure recovery for before outcome generation, after outcome persistence, and after result display. Never regenerate a persisted outcome to alter a round.
6. Explicit owner approval of the complete specification.

## Do not do yet

Do not implement payout or betting code. Do not silently choose missing rules. Do not mark P00-T02 complete or update locked requirements as approved until the owner explicitly approves the full specification.
