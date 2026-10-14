# Next Action

## Active task

**P00-T02 — Finalize approved roulette payout/settlement specification gates.**

## Objective

Owner approval was received on 2026-10-14. Next, complete and review the canonical legal-position catalogue before any betting-engine implementation.

## Current draft

See [Roulette Payout and Settlement Specification (Draft)](roulette/PAYOUT_AND_SETTLEMENT_SPEC_DRAFT.md). It records the latest owner instructions and the selected atomic server-failure recovery policy. The owner approved the specification on 2026-10-14; the legal-position catalogue remains a pre-implementation gate.

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

## Approval and next gate

- Owner approval of the complete payout/settlement specification recorded on 2026-10-14.
- Next: document and review the exact canonical legal-position catalogue, especially zero-adjacent combinations.
- Do not start betting-engine implementation until the catalogue and relevant acceptance criteria are verified.

## Do not do yet

Do not implement betting or payout code yet. Owner approval is recorded, but do not mark P00-T02 complete until the canonical legal-position catalogue and remaining acceptance criteria are verified.
