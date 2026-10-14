# Next Action

## Active task

**P00-T02 — Approve roulette bet types and payout rules.**

## Objective

Resolve remaining interpretations and obtain explicit approval of the complete V1 bet catalogue and settlement rules before implementing the betting engine.

## Current draft

See [Roulette Payout and Settlement Specification (Draft)](roulette/PAYOUT_AND_SETTLEMENT_SPEC_DRAFT.md). It records the latest owner instructions and a labelled server-failure recovery recommendation. It remains unapproved.

## Latest owner rules recorded

- Total payout includes the stake; a 10-coin straight-up win credits 350 coins total.
- One shared server-authoritative result; individual bet data stays private to each player.
- Chips: 5, 10, 50, 100, 500; minimum stake 5.
- Straight-up and split bets share a 2,000-coin exposure cap per underlying number.
- 2,000-coin combined cap per player, per round, per exact Red, Black, dozen, column, street/row, Odd, Even, corner, six-line, first-four, and Low/High selection.
- Duplicate selections remain separate records but display a combined stake.
- Players edit/cancel local bet drafts before submission; accepted bets are immutable.
- If a stake exceeds the applicable cap, the draft proposes accepting only the valid remaining amount and immediately returning the excess, subject to chip rules.
- Rebet repeats the player's own prior-round set all-or-nothing; accepted rebet bets are immutable.
- Seconds 0–44 betting open; second 45 final-bet call; second 50 close/freeze bets and start animation; second 60 reveal and settle.
- Player internet disconnection after acceptance does not cancel a bet.
- Owner-selected server/game-failure policy: use atomic round settlement; if settlement cannot commit, void/refund all accepted stakes idempotently; if settlement has committed, do not refund again; never regenerate a persisted outcome. If an outcome was persisted but settlement cannot commit, retain it for audit and void/refund.
- Standard European single-zero layout only.

## Owner choices confirmed on 2026-10-14

- The 2,000-coin combined cap also applies to each exact corner, six-line, first-four, and Low/High selection.
- “Rows” means street bets.
- Editing/cancellation is local-draft-only before submission; accepted bets are immutable.
- Atomic settlement/refund policy is selected: refund accepted stakes if settlement cannot commit; do not refund after a successful settlement commit; never regenerate a persisted outcome.

## Remaining decisions before approval

1. Review the canonical legal-position catalogue, especially zero-adjacent bets.
2. Explicit owner approval of the complete specification.

## Do not do yet

Do not implement betting or payout code. Do not silently resolve open rules. Do not mark P00-T02 complete or update locked requirements as approved until the owner explicitly approves the full specification.
