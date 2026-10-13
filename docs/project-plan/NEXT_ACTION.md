# Next Action

## Active task

**P00-T02 — Approve roulette bet types and payout rules.**

## Objective

Write and approve the complete V1 bet catalogue and settlement rules before implementing the betting engine.

## Required decisions

- Which inside bets are supported (for example, straight, split, street, corner, six line).
- Which outside bets are supported (for example, red/black, odd/even, low/high, dozens, columns).
- Exact payout multipliers and whether they are expressed as net winnings or total return.
- Treatment of zero for every bet type.
- Whether a player may place multiple bets of the same type and/or on the same selection.
- Minimum stake policy, chip combination rules, and handling of insufficient balance.
- Whether bets can be edited/cancelled before betting closes.
- Settlement rounding and ledger entry rules.

## Acceptance criteria

1. A written, unambiguous table covers every supported bet type, valid selection, stake, and payout.
2. Zero behavior and edge cases are explicit.
3. Rules are consistent with European roulette and are not altered to manipulate outcomes.
4. Product owner approves the document before P08/P11 implementation.
5. Requirements and traceability documents are updated to match the approved rules.

## Do not do yet

Do not implement payout code or silently choose missing bet rules. Record open questions and ask for approval.
