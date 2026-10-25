# FairMount Roulette — Cap and Partial-Acceptance Edge-Case Matrix

**Status:** Owner decisions recorded on 2026-10-14; specification verification draft — not implementation or test evidence  
**Prerequisites:** Owner-approved payout/settlement specification and canonical legal-position catalogue  
**Purpose:** Define deterministic cases for private engine regression and eventual public/gameplay acceptance; this document alone does not authorize release.

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
- For split bets, the stake counts against both constituent numbers. The accepted amount is limited by the smaller remaining per-number capacity; there is no separate exact-split cap in the locked rules.
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
| PA-05 | Defensive invariant test: inject or simulate an invalid internal state where computed cap capacity is 1–4 coins, despite accepted stakes and caps normally being multiples of 5 | The acceptance service must never accept a stake below 5 or a non-multiple of 5; reject without wallet/exposure mutation and emit an invariant/error signal. This state is unreachable through valid operations and is not a normal gameplay scenario |
| PA-06 | Straight-up 17 already has 1,995 exposure; request 10 on 17 | Accept 5; return 5; total exposure becomes 2,000 |
| PA-07 | Straight-up 17 already has 1,500 exposure; request 1,000 on split 17/20; number 20 and other applicable limits have sufficient capacity | Accept at most 500 because number 17 has only 500 exposure capacity remaining; return remainder |
| PA-08 | Split 17/20 has 1,500 accepted; request another 1,000 on the same split | Accept at most 500 because each constituent number has only 500 exposure capacity remaining; return remainder. Do not apply an additional exact-split cap unless the locked requirements are explicitly amended |
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
| PA-22 | Settlement fails or result is missing after cutoff | Under D-06a, independently persist a missing result once and settle even late; if result persisted, retry that result and settle. Do not auto-void or refund for a timeout/failure. Separately authorized exceptional pre-result void, if later approved, must refund each accepted stake once without payout. |
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

## 4. Review of PA-01 through PA-23

The matrix was reviewed against the locked requirements; PA-22 was later revised for owner-approved D-06a (no automatic failure void). PA-01–PA-04, PA-06–PA-21 and PA-23 are consistent after clarifying PA-07 and PA-08: the locked requirements define the per-number exposure cap for straight-up and split bets, but do not define a separate exact-split cap. Those cases therefore derive the 500-coin limit from the remaining exposure on the constituent number(s), not an extra split-selection cap. PA-05 needed clarification: because all accepted stakes and both caps are multiples of 5, a 1–4 coin remaining capacity cannot occur through valid operations. It is retained as a defensive invariant/corrupt-state test, not a normal acceptance scenario.

Implementation test layers:

- **Pure unit tests:** PA-01–PA-10, PA-14–PA-16, PA-20–PA-21; include exact accepted amount, excess return, normalization, and no-side-effect assertions.
- **Database/transaction integration tests:** PA-17–PA-18 and PA-22–PA-23; assert ledger, wallet, accepted-bet records, idempotency keys, and terminal round state.
- **Concurrency tests:** PA-11–PA-12 using genuinely overlapping requests and the production database transaction/locking strategy; assert no cap or wallet overspend.
- **Round lifecycle tests:** PA-13 against server-authoritative cutoff state, not a client timer.
- **Rebet atomicity tests:** PA-19, including balance failure, cap failure, and rollback of the entire set.
- **Authorization tests:** separately test that one player cannot read another player's bets or private realtime payloads.

The original eight catalogue tests validate catalogue fixture invariants only. Later private betting/settlement services have separate PostgreSQL evidence; fixture tests alone do not establish a public game or complete PA end-to-end acceptance.

## 5. Remaining integration gate

This matrix is a test specification, not proof of complete gameplay acceptance. Before any public game/release claim:
1. The canonical red/black sets and all catalogue counts must be represented in the deterministic fixture and the catalogue suite must pass.
2. The acceptance criteria must be reviewed and testable (review recorded above).
3. The implementation plan must include concurrency, transaction rollback, idempotency, rebet atomicity, cutoff, and settlement/refund tests.
4. Tests must run against the actual implementation and supported database before any implementation task is declared verified.

This matrix does not itself authorize public betting, automatic incident voids or release. Private engine slices were subsequently implemented and tested; API/realtime privacy, full PA coverage and operational gates remain open.
