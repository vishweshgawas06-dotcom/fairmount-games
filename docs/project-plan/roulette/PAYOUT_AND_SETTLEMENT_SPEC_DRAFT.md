# P00-T02 — Roulette Payout and Settlement Specification (Draft)

**Status:** Draft for owner review — NOT APPROVED  
**Implementation status:** Not implemented  
**Purpose:** Record the current user-confirmed requirements and make remaining interpretations visible before coding.

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

## 3. Bet limit

Current user requirement: each player has a maximum permitted bet amount of 2,000 coins, and this is **not an aggregate cap on the total amount bet during an entire round**.

Implementation interpretation to verify before coding: enforce 2,000 coins as the maximum stake for each individual bet selection; allow multiple distinct selections in the same round, subject to the available wallet balance. The earlier proposed 3,000-coin cap for other bet categories is superseded by the latest 2,000-coin requirement unless the owner explicitly revises it.

## 4. Rebet

- Provide a Rebet button for every player.
- Rebet repeats that player's own previous-round bet set, preserving the selections and amounts; it must never copy another player's bets.
- Check that the player's available wallet balance is sufficient for the total stake of the complete repeated set.
- If insufficient, place none of the rebet and show a clear message.
- If sufficient, place the repeated set through the same server-side validation, wallet reservation, bet-limit, and cutoff checks as normal bets.
- After the rebet is placed, the player may add bets, remove selections, or change their bets while betting remains open.
- The rebet operation must be atomic: do not partially place the previous set if the balance is insufficient or if any required validation fails.
- The previous bet set is the current player's own most recent placed set, not a shared/global bet set.

## 5. Round timing and settlement

- Seconds 0–44: betting open; accepted bets may be edited or removed.
- At second 45: show the final-bet call/warning; betting remains open until the cutoff.
- At second 50: server closes betting, rejects new bets and edits, and freezes the accepted bet set. The roulette wheel and ball animation begins.
- Generate and persist exactly one server-authoritative outcome per global round, independently of all bets, balances, and player identities. The animation must land on the already determined result; animation never determines the result.
- At second 60: reveal/display the winning number, calculate each player's combined winning payout, and update the player's wallet. Start the next round according to the authoritative round clock.
- Only server-confirmed accepted bets before the cutoff are valid. Client-side timestamps or UI state do not establish acceptance.
- Settlement must be idempotent and protected by database transactions/constraints so a retry or reconnect cannot credit a player twice.

## 6. Zero and supported bet catalogue

- Zero is the single green pocket 0.
- Zero does not qualify as red/black, odd/even, low/high, dozen, or column.
- No La Partage or En Prison is currently proposed.
- Inside bets: straight-up, split, street, corner, six line, and first four.
- Outside bets: dozen, column, red/black, odd/even, and low/high.
- The server must validate each inside-bet selection against the defined European roulette table layout.
- Overlapping bets settle independently.

## 7. Remaining approval items

- Confirm whether the 2,000-coin limit is per individual selection as stated in Section 3.
- Confirm duplicate identical selections are allowed as separate bet records or combined in the display.
- Confirm the void-round policy and any exceptional handling when the system cannot safely complete a round.
- Confirm exact table-layout mapping for zero-containing splits/streets and the first-four bet.
- Owner approval of the complete P00-T02 specification is still required before implementation.

