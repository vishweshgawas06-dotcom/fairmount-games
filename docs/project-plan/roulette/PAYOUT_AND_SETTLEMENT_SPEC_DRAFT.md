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

## 3. Chips and stake limits

- Allowed chip denominations: 5, 10, 50, and 100, 500 coins. Minimum positive stake: 5 coins.
- A player may bet on multiple selections in a round, subject to available balance and the caps below.
- **Straight-up number exposure:** at most 2,000 coins of accepted stake exposure on any one number across straight-up bets and split bets that include that number. Separate bet records remain separate, but the cap is aggregated per underlying number.
- Example: if 1,500 coins are already placed straight-up on 17, no more than 500 additional coins of exposure to 17 can be accepted from another straight-up or split bet. Any excess is returned to the wallet.
- A split bet contributes its accepted stake to the exposure of both numbers in that split. Its accepted amount cannot exceed the smaller remaining cap of the two numbers; return the unaccepted remainder. Validate atomically.
- **Per-selection caps:** a 2,000-coin combined maximum applies per player, per round, per exact selection for Red, Black, each dozen, each column, each street/row, Odd, Even, each corner, each six-line, the first-four selection, and each Low/High selection. Duplicate records of the same exact selection count toward that selection's combined cap.
- These per-selection caps are separate from the 2,000-coin exposure cap per underlying number across straight-up and split bets. Apply every relevant cap independently; satisfying one cap does not bypass another.
- If a submission exceeds an applicable cap, accept only the valid amount remaining under the relevant cap(s) and immediately return the unaccepted remainder, provided the accepted amount satisfies the minimum stake and allowed chip rules. Otherwise reject it without changing the wallet.

## 4. Duplicate selections and bet finality

- Duplicate identical selections remain separate bet records, while the interface clearly displays their combined stake.
- Players edit or cancel bets in a local draft before submission; draft changes do not reserve or deduct wallet coins.
- On submission, the server validates the request and confirms acceptance or rejection. Once the server confirms a bet as accepted, it is immutable: it cannot be edited, cancelled, or withdrawn. Additional stake must be submitted as a new bet and validated against wallet balance, exposure limits, and cutoff.
- The client must distinguish a local draft, a pending submission, and a server-confirmed accepted bet. A click or client-side display is not proof of acceptance.
- If a requested stake exceeds an applicable cap, accept only the valid amount remaining under the cap and immediately return the unaccepted remainder, provided the accepted amount is at least 5 and conforms to the allowed chip denominations. If no valid amount can be accepted, reject the submission and leave the wallet unchanged.
- Prevent concurrent submissions from exceeding any per-number or per-selection cap.
- The earlier draft rule allowing already accepted bets to be edited or removed is superseded.

## 5. Rebet

- Provide a Rebet button for every player. It repeats that player's own previous-round bet set and amounts; it never copies another player's bets.
- Validate the full rebet set against available balance, chip rules, number-exposure limits, per-selection limits, and cutoff before accepting.
- If the full set cannot be accepted under all rules, place none and show a clear message. Do not partially rebet.
- Once accepted, each repeated bet is immutable. The player may submit additional new bets while betting remains open, but cannot edit or cancel accepted rebet records.
- Rebet is an atomic operation and uses the player's own most recent placed set.

## 6. Round timing and settlement

- Seconds 0–44: betting open; players may submit bets.
- At second 45: show the final-bet call/warning; betting remains open until the cutoff.
- At second 50: server closes betting, rejects new submissions, and freezes the accepted bet set. Wheel/ball animation begins.
- Generate and persist exactly one server-authoritative outcome per global round, independently of bets, balances, and player identities. Animation lands on the already determined result; it never determines the result.
- At second 60: reveal the winning number, calculate each player's combined winning payout, and update wallets. Start the next round according to the authoritative clock.
- Only server-confirmed accepted bets before cutoff are valid. Client timestamps/UI do not establish acceptance.
- Settlement must be transactional and idempotent so retries or reconnects cannot credit a player twice.

## 7. Zero and supported bet catalogue

- Zero is the single green pocket 0 and does not qualify as Red/Black, Odd/Even, Low/High, dozen, or column.
- No La Partage or En Prison is proposed.
- Inside bets: straight-up, split, street, corner, six line, and first four. Outside bets: dozen, column, Red/Black, Odd/Even, and Low/High.
- Use only valid standard selections on the standard single-zero European layout; no custom bet types or nonstandard positions.
- Overlapping bets settle independently.
- A canonical list of valid positions, including zero-adjacent positions, must be reviewed before implementation.

## 8. Internet disconnection and server/game failure

- **Player-side internet disconnection after acceptance:** accepted bets remain valid and settle normally against the shared winning number. Disconnection does not cancel or change the bet. On reconnect, return authoritative balance, round, result, and the player's own bet state.
- **Owner-selected atomic recovery rule:** settlement for a global round is one atomic transaction. If a server/game-side failure prevents the settlement transaction from committing successfully, void the round and refund all accepted stakes for that round through idempotent ledger entries. If settlement commits successfully, do not issue a later refund for that same round/stake. Record the incident/void reason and refund entries; do not leave stakes frozen pending manual review.
- Generate and persist at most one outcome per round. Never generate a replacement outcome if an outcome has already been persisted. If a persisted outcome exists but settlement cannot safely commit, void/refund according to the atomic recovery rule while retaining the persisted outcome for audit; never pay and refund the same stake.
- Each round must end in one terminal accounting state (for example, settled or void-refunded), enforced through transactional state transitions and unique ledger references.
- A player disconnect must not be classified as a server/game-side failure.

## 9. Valid standard European table positions

- Use the standard single-zero European roulette table.
- Validate selections server-side against a canonical list of legal straight-up, split, street, corner, six-line, and first-four combinations.
- First four is exactly {0, 1, 2, 3}.
- The complete machine-readable catalogue, including legal positions adjacent to zero, is a prerequisite before the betting engine is built.

## 10. Remaining ambiguities and approval gates

1. **Canonical layout catalogue:** Review the exact valid standard positions, especially zero-adjacent combinations, before implementation.
2. **Owner approval:** Explicit approval of the complete consolidated specification remains required before implementation.

### Owner choices recorded on 2026-10-14

- Apply the 2,000-coin combined per-player/per-round cap to each exact corner, six-line, first-four, and Low/High selection as well as the previously listed selection types.
- Interpret “rows” as street bets.
- Use local bet drafts that can be edited/cancelled before submission; accepted bets are immutable.
- Use atomic settlement/refund recovery: if settlement cannot commit, void/refund accepted stakes idempotently; if settlement commits, do not refund again; never regenerate a persisted outcome.

## 11. Approval status

This draft records the owner's latest instructions, including the four choices listed above. These choices do **not** constitute approval of the complete specification. P00-T02 remains open; no betting-engine implementation is authorized.
