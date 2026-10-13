# P00-T02 — Roulette Payout and Settlement Specification (Draft)

**Status:** Draft for owner review — NOT APPROVED  
**Implementation status:** Not implemented  
**Purpose:** Record owner-provided choices and make remaining interpretations visible before coding.

## 1. Global game and individual player view

- Use a single-zero European roulette wheel with pockets 0–36.
- All active players participate in the same server-authoritative global round and receive the same winning number.
- Each player sees their own roulette table/interface and their own accepted bets only.
- A player must never see the amounts or selections bet by other players. Do not expose other players' bet data through the UI, WebSocket messages, APIs, or client state.
- Each player sees their own balance, their own bets, winning numbers, and their own game history as otherwise specified in the project requirements.

## 2. Payout convention

Use the original conventional European roulette payout ratios, but the multiplier is applied to the stake to calculate the **total payout credited**, including the stake. Do not add the stake again.

**Formula:** `total payout = winning stake × listed multiplier`

| Bet type | Multiplier used for total payout | Example: 10-coin winning stake | Total payout credited |
|---|---:|---:|---:|
| Straight-up | 35× | 10 × 35 | 350 |
| Split | 17× | 10 × 17 | 170 |
| Street | 11× | 10 × 11 | 110 |
| Corner | 8× | 10 × 8 | 80 |
| Six line | 5× | 10 × 5 | 50 |
| First four (0, 1, 2, 3) | 8× | 10 × 8 | 80 |
| Dozen | 2× | 10 × 2 | 20 |
| Column | 2× | 10 × 2 | 20 |
| Red / Black | 1× | 10 × 1 | 10 |
| Odd / Even | 1× | 10 × 1 | 10 |
| Low / High | 1× | 10 × 1 | 10 |

These multipliers intentionally differ from conventional casino total-return figures: the requested product rule uses the listed conventional *net-profit ratios* as the multiplier for the *entire credited payout*. For example, a 10-coin straight-up win credits 350 coins total, not 360.

- Deduct/reserve stakes when bets are accepted.
- For a winning bet, credit the total payout once; do not separately return the stake.
- For a losing bet, the stake remains lost and there is no payout.
- If multiple bets win in one round, calculate all returns, sum them for that player, and credit the aggregate amount to that player's wallet at the result-reveal time.
- Track bet-level settlement and wallet ledger entries so the accounting can be audited and retries cannot pay twice.
- Gameplay P/L must be calculated consistently with the total-return convention and must not double-count the stake.

## 3. Bet limits and stake increments

- Maximum stake is 2,000 coins for each individual bet selection. This is not a maximum for the total amount bet during a round. Multiple selections are allowed subject to available wallet balance.
- The 2,000-coin cap applies to every bet type; the earlier proposed 3,000-coin cap for other bet categories is superseded.
- Owner choice: use only chip denominations 5, 10, 50, 100, and 500 coins; minimum stake is 5 coins.
- The final accepted stake for a bet must be buildable from the allowed chips; the smallest possible positive stake is 5 coins. Whether repeated identical selections share one combined 2,000-coin cap is still unresolved (see Section 9).

## 4. Duplicate selections and bet edits

- Owner choice: duplicate identical selections are retained as separate bet records, while the interface clearly displays their combined stake for that selection.
- Owner choice: edits are atomic. Validate the full requested change first; either accept the complete change or leave the existing accepted bet state unchanged.
- No partial edit may be applied if the full edit fails validation, balance checks, the per-selection cap, or the betting cutoff.
- Exact cap aggregation across duplicate records and the precise scope of a multi-selection edit remain open questions in Section 9.

## 5. Rebet

- Provide a Rebet button for every player.
- Rebet repeats that player's own previous-round bet set, preserving the selections and amounts; it must never copy another player's bets.
- Check that the player's available wallet balance is sufficient for the total stake of the complete repeated set.
- If insufficient, place none of the rebet and show a clear message.
- If sufficient, place the repeated set through the same server-side validation, wallet reservation, bet-limit, and cutoff checks as normal bets.
- After the rebet is placed, the player may add bets, remove selections, or change their bets while betting remains open.
- The rebet operation must be atomic: do not partially place the previous set if the balance is insufficient or if any required validation fails.
- The previous bet set is the current player's own most recent placed set, not a shared/global bet set.

## 6. Round timing and settlement

- Seconds 0–44: betting open; accepted bets may be edited or removed.
- At second 45: show the final-bet call/warning; betting remains open until the cutoff.
- At second 50: server closes betting, rejects new bets and edits, and freezes the accepted bet set. The roulette wheel and ball animation begins.
- Generate and persist exactly one server-authoritative outcome per global round, independently of all bets, balances, and player identities. The animation must land on the already determined result; animation never determines the result.
- At second 60: reveal/display the winning number, calculate each player's combined winning payout, and update the player's wallet. Start the next round according to the authoritative round clock.
- Only server-confirmed accepted bets before the cutoff are valid. Client-side timestamps or UI state do not establish acceptance.
- Settlement must be idempotent and protected by database transactions/constraints so a retry or reconnect cannot credit a player twice.

## 7. Zero and supported bet catalogue

- Zero is the single green pocket 0.
- Zero does not qualify as red/black, odd/even, low/high, dozen, or column.
- No La Partage or En Prison is currently proposed.
- Inside bets: straight-up, split, street, corner, six line, and first four.
- Outside bets: dozen, column, red/black, odd/even, and low/high.
- Use the standard European roulette layout; only valid standard selections are allowed. Custom bet types or nonstandard positions are not included.
- Overlapping bets settle independently.
- Exact canonical position mapping for all inside bets, including zero-containing split/street positions, corners/six lines adjacent to zero, and first four, must be written as an explicit validated selection catalogue before implementation.

## 8. Void-round handling

- Owner choice: if a round cannot safely complete, freeze settlement for owner/admin review.
- This choice does not yet specify the admin decision options, whether/when stakes are refunded, whether the round outcome is retained or voided, or how the next round proceeds. These remain open and must not be guessed by implementation.

## 9. Remaining ambiguities and approval gates

1. **Duplicate-selection cap:** Does the 2,000-coin limit apply to the combined stake across all separate records for the same exact selection, or to each separate record independently? The UI will show a combined total either way.
2. **Edit scope:** Is an atomic edit one user action affecting one selection, or may one action edit several selections and must then succeed/fail as a whole? Suggested default for review: each submitted edit operation is one atomic unit; multi-selection edits are all-or-nothing.
3. **Void-round admin decision:** What explicit actions can owner/admin take after settlement is frozen (for example, void and refund all accepted stakes, or resume settlement using the already-persisted outcome)? What happens if no decision is made promptly?
4. **Canonical layout catalogue:** Confirm/record the full set of valid standard positions for zero-adjacent inside bets and first four. The rule is standard European layout only; the exact machine-readable mapping is not yet attached.
5. **Outcome timing on exceptional failure:** If a failure occurs before an outcome is generated, or after it is persisted but before result display/settlement, should the system generate an outcome, reuse the persisted outcome, or freeze for review? Outcome must never be regenerated to change a round already persisted.
6. **Owner approval:** Approval of the complete specification is still required before implementation.

## 10. Approval status

This document is a draft that records the owner's five latest choices. Those choices do **not** constitute approval of the entire specification. P00-T02 remains open; no betting-engine implementation is authorized by this draft.
