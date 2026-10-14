# FairMount Roulette — Cap and Partial-Acceptance Edge-Case Matrix

**Status:** Owner decisions recorded on 2026-10-14; specification verification draft — not implementation or test evidence  
**Prerequisites:** Owner-approved payout/settlement specification and canonical legal-position catalogue  
**Purpose:** Define deterministic cases that must pass before betting-engine implementation is authorized.

## 1. Shared acceptance algorithm requirements

For every new bet submission, the server must evaluate the complete canonical selection, betting cutoff, current wallet balance, accepted stake records in the current round, per-selection cap (where applicable), and per-number exposure cap (for straight-up and split bets). This must be one concurrency-safe operation so simultaneous requests cannot overrun a cap or spend the same balance twice.

- Minimum accepted stake: 5 coins.
- Stake amounts and accepted partial amounts must be in increments of 5 coins, because every available chip is a multiple of 5.
- Never accept less than 5 coins. If the valid remaining amount is below 5, reject that bet without debiting the wallet.
- For an otherwise valid cap-limited bet, accept the largest valid amount not exceeding the requested amount and all applicable remaining caps; return the unaccepted excess immediately.
- Accepted stake is reserved/debited once. The excess refund and stake reservation must be atomic with acceptance, so a failure cannot leave a partial wallet mutation.
- If a bet is rejected, neither balance nor cap usage changes.
- Rejected/returned excess must not be recorded as accepted exposure.
- A duplicate selection is a distinct bet record but contributes to the same aggregate canonical-selection cap.
- For split bets, the stake counts against both constituent numbers. The accepted amount is limited by the smaller remaining per-number capacity as well as the split-selection cap.
- The per-selection caps and per-number exposure caps are independent constraints; apply all constraints that match the bet.
- Rebet remains a separate all-or-nothing operation for the player's complete previous-round set. Do not partially rebet.
- For an ordinary bet, if the player's balance is less than the requested stake, reject the entire bet and preserve the balance unchanged. Do not balance-limit or partially accept an ordinary bet.
- Cap-limited partial acceptance remains allowed only when the player can cover the full requested stake and the applicable cap(s), rather than balance, are the only limiting factor. Reserve the accepted amount and return cap-excess atomically. If balance is insufficient for the original request, reject it without any wallet or cap mutation.

## 2. Required verification matrix

| ID | Setup / request | Expected result |
|---|---|---|
| PA-01 | New legal 10-coin bet; balance and all caps sufficient | Accept 10; debit/reserve 10 once |
| PA-02 | Requested 500; only 15 remains under applicable cap | Accept 15; return 485; exposure rises by 15 |
| PA-03 | Requested 10; only 5 remains under applicable cap | Accept 5; return 5 |
| PA-04 | Requested 10; 0 remains under any applicable cap | Reject; no wallet or exposure mutation |
| PA-05 | Requested amount would leave only 1–4 coins of cap capacity | Accept only the largest multiple of 5 within capacity if at least 5; otherwise reject. Existing accepted stakes are multiples of 5, so cap capacity should itself remain a multiple of 5 |
| PA-06 | Straight-up 17 already has 1,995 exposure; request 10 on 17 | Accept 5; return 5; total exposure becomes 2,000 |
| PA-07 | Straight-up 17 already has 1,500 exposure; request 1,000 on split 17/20; both number and split-selection caps otherwise unused | Accept at most 500, subject to all other applicable limits; return remainder |
| PA-08 | Split 17/20 has 1,500 accepted; request another 1,000 on same split | Accept at most 500 under the exact split-selection cap, also constrained by both numbers' remaining exposure; return remainder |
| PA-09 | Split includes number A with 200 capacity remaining and number B with 700 remaining; request 500 | Accept at most 200, subject to split-selection cap; return remainder |
| PA-10 | Duplicate bet records on the same exact corner; aggregate is 1,995; request 10 | Accept 5; return 5; preserve separate accepted records |
| PA-11 | Straight-up and split requests race to consume the same number's remaining exposure | Serialized/locked acceptance allows no aggregate exposure above 2,000; loser request is partially accepted or rejected according to remaining valid capacity |
| PA-12 | Two duplicate outside-bet requests race for the same exact selection cap | Aggregate accepted stake never exceeds 2,000 |
| PA-13 | Selection is legal but second 50 cutoff has committed | Reject regardless of client timer state |
| PA-14 | Selection contains illegal number set, diagonal split, unsupported zero corner, or arbitrary outside number list | Reject; no wallet/cap mutation |
| PA-15 | Request uses reversed number order for a legal split/corner/six-line | Normalize to the same canonical selection; caps aggregate together |
| PA-16 | Same numbers but different bet type (e.g. First Four vs generic corner) | Validate using bet type and catalogue; First Four is its own type and not a generic corner |
| PA-17 | Accepted bet followed by client retry with same idempotency key | Return original result; do not reserve/debit twice |
| PA-18 | Acceptance transaction fails after internal work begins | Roll back all wallet, accepted-bet, cap/exposure, and ledger changes |
| PA-19 | Rebet set total exceeds balance or any bet in the set cannot be accepted under current caps | Reject the entire rebet; no partial rebet or partial debit |
| PA-20 | Ordinary 20-coin bet with 12-coin balance; caps otherwise allow it | Reject entire bet; balance remains 12; no bet record or exposure change |
| PA-21 | Balance is 12 and ordinary requested stake is 15; caps otherwise allow it | Reject entire bet; balance remains 12. A wallet balance not divisible by 5 does not permit balance-limited partial acceptance. |
| PA-22 | Round is voided after settlement failure | Refund every accepted stake once, idempotently; no payout is credited for the voided round |
| PA-23 | Settlement has committed and a retry/recovery worker runs | No refund; no duplicate payout; terminal state remains settled |

## 3. Required automated assertions

- Catalogue counts match the owner-approved catalogue: straight-up 37; splits 60 (24 horizontal, 33 vertical, 3 zero); streets 14 (12 numbered, 2 zero-adjacent); generic corners 22; six-lines 11; First Four 1.
- Red/black sets are fixed canonical lists, each disjoint, exclude zero, and together cover 1–36.
- Every selection's number set matches the approved type-specific catalogue.
- Per-number exposure and per-selection caps never exceed 2,000 under sequential or concurrent requests.
- All accepted stake amounts are >= 5 and multiples of 5.
- Partial acceptance plus returned excess equals the requested amount whenever the request is otherwise valid and cap-limited.
- Rejected requests have no accounting side effects.
- Ledger and wallet balance remain consistent after retries, transaction failures, settlement, and void/refund.
- One request's idempotency key cannot create multiple accepted bets or wallet mutations.
- Player-private bet data remains inaccessible to other players through API and realtime payloads.

## 4. Gate before implementation

This matrix is a test specification, not evidence that tests have run. Do not begin betting-engine implementation until:
1. The canonical red/black sets and all catalogue counts are represented in a deterministic test fixture.
2. The acceptance criteria are reviewed and testable.
3. The implementation plan includes concurrency, transaction rollback, and idempotency tests.

No betting-engine implementation is authorized by this document.
