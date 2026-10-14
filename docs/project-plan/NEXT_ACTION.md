# Next Action

## Active task

**P00-T02 — Execute catalogue fixture tests and verify cap/partial-acceptance criteria.**

## Objective

The owner approved the payout/settlement specification and canonical legal-position catalogue on 2026-10-14. The owner reports that the deterministic catalogue suite passed locally on 2026-10-14 (8 tests, 0 failures). PA-01 through PA-23 have now been reviewed against the locked requirements; PA-05 is clarified as a defensive invariant test for an unreachable invalid state, and PA-07/PA-08 now correctly derive split limits from per-number exposure (no separate exact-split cap is defined in locked requirements). The next step is to define concrete engine test cases and prepare the minimal betting-engine architecture before writing engine code. Do not skip the verification plan.

## Verification artifacts

- [Canonical catalogue fixture](../../tests/fixtures/roulette_catalogue.json)
- [Catalogue fixture tests](../../tests/test_roulette_catalogue_fixture.py)
- [Cap and partial-acceptance edge cases](roulette/CAP_PARTIAL_ACCEPTANCE_EDGE_CASES.md)
- [Canonical legal-position catalogue](roulette/LEGAL_POSITION_CATALOGUE_REVIEW.md)

The fixture/test files are specification verification artifacts only. The reported passing suite validates catalogue invariants, not bet acceptance or settlement behavior. No betting-engine implementation has been written.

## Latest owner rules

- Total payout includes the stake; a 10-coin straight-up win credits 350 coins total.
- One shared server-authoritative result; individual bet data stays private to each player.
- Chips: 5, 10, 50, 100, 500; minimum stake 5.
- Straight-up and split bets share a 2,000-coin exposure cap per underlying number.
- 2,000-coin combined cap per player, per round, per exact Red, Black, dozen, column, street/row, Odd, Even, corner, six-line, first-four, and Low/High selection.
- Duplicate selections remain separate records but display a combined stake.
- Players edit/cancel local bet drafts before submission; accepted bets are immutable.
- Ordinary bets are rejected in full when the wallet cannot cover the requested stake. Cap-limited partial acceptance is allowed only if the full requested stake is affordable.
- Rebet repeats the player's own prior-round set all-or-nothing; accepted rebet bets are immutable.
- Seconds 0–44 betting open; second 45 final-bet call; second 50 close/freeze bets and start animation; second 60 reveal and settle.
- Player internet disconnection after acceptance does not cancel a bet.
- If settlement cannot commit, void/refund accepted stakes idempotently; if settlement has committed, do not refund again; never regenerate a persisted outcome.
- Standard European single-zero layout only.

## Approval and verification status

- Owner approval of the payout/settlement specification and canonical catalogue recorded on 2026-10-14.
- Catalogue fixture suite reported passing locally: 8 tests, 0 failures, using `python -m unittest discover -s tests -v` from the repository root.
- PA-01 through PA-23 reviewed; PA-05 clarified as an unreachable-state defensive invariant test; PA-07/PA-08 aligned with per-number split exposure rules. Test layers are specified for unit, database/transaction, concurrency, cutoff, rebet, settlement/refund, and player-privacy authorization behavior.
- Next: draft/confirm the betting-engine architecture and concrete test implementation plan (including database locking, atomic ledger/wallet updates, idempotency, and failure injection) before writing engine code.
- No engine code exists yet; passing catalogue tests do not authorize treating cap or settlement behavior as verified.

## Do not do yet

Do not implement betting or payout code yet. Owner approval locks the requirements; it does not waive verification gates.
