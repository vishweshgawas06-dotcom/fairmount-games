# Next Action

## Active task

**P00-T02 — Approve roulette bet types and payout rules.**

## Objective

Resolve the remaining interpretations and obtain explicit approval of the complete V1 bet catalogue and settlement rules before implementing the betting engine.

## Current draft

See [Roulette Payout and Settlement Specification (Draft)](roulette/PAYOUT_AND_SETTLEMENT_SPEC_DRAFT.md). It records the latest owner instructions and a labelled failure-recovery recommendation. It remains unapproved.

## Latest owner rules recorded

- Total payout includes the stake; a 10-coin straight-up win credits 350 coins total.
- One shared server-authoritative result; individual bet data stays private to each player.
- Chips: 5, 10, 50, 100, 500; minimum stake 5.
- Straight-up and split bets share a 2,000-coin exposure cap per underlying number.
- Intended 2,000-coin combined cap per player, per round, per exact Red, Black, dozen, column, Odd, Even, and row/street selection.
- Duplicate selections remain separate records but display a combined stake.
- Bets may be edited/cancelled only before server acceptance; accepted bets are immutable.
- Over-cap requests are proposed to accept only the remaining valid stake and return the excess immediately, subject to chip rules.
- Rebet repeats the player's own prior-round set all-or-nothing; accepted rebet bets are immutable.
- Seconds 0–44 betting open; second 45 final-bet call; second 50 close/freeze bets and start animation; second 60 reveal and settle.
- Player internet disconnection after acceptance does not cancel a bet.
- Server/game-side failure that prevents safe completion should trigger automatic audited refunds; reuse any persisted outcome if safe and never regenerate a persisted outcome.
- Standard European single-zero layout only.

## Remaining decisions before approval

1. Confirm the cap treatment for corner, six-line, first-four, and Low/High.
2. Confirm “rows” means street/row bets.
3. Confirm partial acceptance and immediate excess refund behavior.
4. Confirm local-draft editing before submission and immutable accepted bets.
5. Review the canonical legal-position catalogue, especially zero-adjacent bets.
6. Confirm the proposed server-failure recovery and no-double-pay/refund safeguard.
7. Explicit owner approval of the complete specification.

## Do not do yet

Do not implement betting or payout code. Do not silently resolve open rules. Do not mark P00-T02 complete or update locked requirements as approved until the owner explicitly approves the full specification.
