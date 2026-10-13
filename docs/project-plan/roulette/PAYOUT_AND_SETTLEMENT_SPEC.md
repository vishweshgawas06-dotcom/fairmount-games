# FairMount Roulette — Proposed Payout and Settlement Specification

**Status: PROPOSED — NOT APPROVED**  
**Task:** P00-T02  
**Purpose:** Resolve payout, per-player privacy, bet limits, rebet, and round timing before implementation.

## 1. Payout convention

Use the same original European roulette payout ratios listed below, but treat the multiplier as the **total payout including the stake**. Do not add the stake to the calculated payout a second time.

Formula for a winning bet:

`total_payout = accepted_stake × original_multiplier`

A losing bet receives a total payout of zero. The accepted stake has already been deducted/reserved from the wallet. Net gameplay profit for a winning bet is `total_payout - accepted_stake`.

| Bet type | Original ratio | Example: 10-coin winning stake | Total payout credited |
|---|---:|---:|---:|
| Straight-up, one number (0–36) | 35:1 | 10 × 35 | 350 |
| Split, two valid adjacent pockets | 17:1 | 10 × 17 | 170 |
| Street, three valid pockets | 11:1 | 10 × 11 | 110 |
| Corner, four valid pockets | 8:1 | 10 × 8 | 80 |
| Six line, six valid pockets | 5:1 | 10 × 5 | 50 |
| First four (0, 1, 2, 3) | 8:1 | 10 × 8 | 80 |
| Dozen | 2:1 | 10 × 2 | 20 |
| Column | 2:1 | 10 × 2 | 20 |
| Red/Black | 1:1 | 10 × 1 | 10 |
| Odd/Even | 1:1 | 10 × 1 | 10 |
| Low/High | 1:1 | 10 × 1 | 10 |

These are deliberately defined as total-return multipliers for this product, not conventional net-profit odds plus returned stake. Example: a 10-coin straight-up win credits 350 coins, not 360. The original stake is not credited again.

## 2. Zero handling and valid selections

- Wheel is European single-zero, pockets 0–36.
- Zero is green and does not qualify as red/black, odd/even, low/high, any dozen, or any column.
- A zero result loses the listed outside bets.
- A straight-up bet on 0 wins at the straight-up multiplier.
- Split/street/corner/six-line selections must match valid positions on the configured European roulette betting layout.
- The special first-four selection covers exactly 0, 1, 2, and 3.
- Overlapping bets settle independently.
- No La Partage or En Prison rule is included in this proposal.

## 3. Individual player table and privacy

- Every player receives their own individual roulette table view and controls.
- Each player sees their own accepted/pending bets, amounts, chips, balance, personal bet history, and the shared winning-number history.
- Players must never see other players' bet selections, stake amounts, individual betting layouts, or personal bet history.
- The round and winning result are global/server-authoritative and shared by all active players. Individual table views do not mean individual outcomes.
- Do not expose other players' bets in API responses, WebSocket events, browser state, logs visible to players, or client-side payloads.
- The player-facing UI must not show aggregate bets or totals that reveal other players' betting activity.

## 4. Stake limits

- Maximum stake for any single bet selection: 2,000 coins.
- This 2,000-coin limit is **not a total-round limit**. A player may place multiple distinct selections in a round, subject to available wallet balance and validation.
- Apply the 2,000-coin cap to each selection, including straight-up numbers and splits; no separate 3,000-coin limit applies to other categories under this proposal.
- Validate the limit on the server. The client UI must not be the enforcement mechanism.
- Chip denominations: 5, 10, 50, 100, and 500 coins.
- Minimum stake and permitted stake increments must be finalized consistently with the chip rules before implementation.
- A bet must be rejected atomically if the player lacks sufficient available balance. Rejection must not partially change the bet or wallet.

## 5. Rebet behavior

- Each player has an individual previous-bet record; it must never be sourced from another player's bets.
- REBET copies that player's own most recent completed betting layout (all selections and amounts from that player's previous round), not the bets of other players.
- Before placing the copied layout, the server checks the total required stake against the player's current available balance and validates each selection and stake limit.
- If the available balance is insufficient for the complete copied layout, reject the rebet as a whole and explain that the balance is insufficient. Do not partially place it.
- If sufficient, accept the copied layout atomically, deduct/reserve the required total stake, and allow the player to edit it before betting closes by adding selections, removing selections, or changing amounts, subject to all rules and available balance.
- REBET is available only while betting is open. A rebet request received after the server cutoff is rejected.
- The server stores and validates the previous-bet snapshot. Client-submitted data is untrusted.
- A rebet is a new set of bets for the current round; it does not reuse the prior round's settlement or transaction IDs.

## 6. Round timing

- Seconds 0–44: betting open; accepted bets can be added, edited, or removed under server validation.
- At second 45: show a clear final-bet-call warning. Betting remains open until the authoritative cutoff at second 50.
- At second 50: close betting on the server, freeze accepted bets, and reject all subsequent bet changes. Begin the wheel-and-ball spin animation. Generate and persist exactly one server-authoritative result independently of all bets, stakes, balances, and player identities.
- Seconds 50–59: animate the wheel and ball toward the already determined result. The animation never determines or changes the result.
- At the 60-second boundary: reveal/display the result, calculate each player's total payout from that player's accepted bets, and credit winnings to that player's wallet.
- Begin the next round on the global schedule. Any implementation detail needed to make second-60 reveal and settlement atomic must preserve the visible timing and exactly-once accounting.
- Bet acceptance is defined by server confirmation, not by when the client began sending a request.

## 7. Settlement and wallet accounting

For each player, sum the total payouts of all winning accepted bets in the round and credit the aggregate amount once at result reveal. Keep individual bet outcomes in the audit/history records.

Example: player starts with 1,000 coins, places 10 coins on number 17 and 20 coins on red, and 17 wins. The accepted stakes total 30 coins, leaving 970 before settlement. Total payouts are 350 + 20 = 370 coins. Final balance is 1,340 coins. The aggregate payout is 370; the original stakes are not added again.

- Winning bet: total payout = stake × the table's original multiplier.
- Losing bet: payout = 0; stake remains lost.
- Gameplay P/L is total payouts minus accepted stakes for that round.
- Administrative point allocations/adjustments remain separate from gameplay P/L.
- Use transactional ledger entries and idempotency keys so retries cannot duplicate deductions, refunds, or payouts.
- Store round ID, player ID, bet IDs, winning result, individual calculated payouts, aggregate credit, and settlement status for audit.
- If a genuine system fault requires voiding a round, the final void/refund procedure still requires explicit product-owner approval before implementation.

## 8. Approval and remaining open items

This document is a proposal, not an approval record. Do not implement the betting engine until the product owner explicitly approves the full P00-T02 specification.

Still requiring explicit resolution/approval:
- Minimum stake and whether every stake must be a combination of the listed chips or merely a multiple of five.
- Duplicate bets on the same selection and how they are represented.
- Exact edit/change semantics for changing a stake after acceptance.
- Void-round handling and refund policy.
- Final approved catalogue/layout mapping for valid inside-bet positions.
- Product-owner approval of this complete specification.
