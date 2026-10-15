# Next Action

## Active task

**P01-T01 — Confirm Python API foundation in GitHub CI (local checks now pass).**

The owner approved the [detailed delivery plan for P00–P19](DETAILED_DELIVERY_PLAN.md) on 2026-10-15 and emphasized a realistic-feeling European roulette machine with a smoothly spinning wheel and ball. The owner separately approved verification of P01-T01. Local Python 3.12 tests, lint, and liveness now pass; CI evidence is still pending. No gameplay implementation was started.

## Objective

The owner-approved roulette specification and catalogue fixture gates are recorded. The owner reported 8/8 catalogue tests passing locally. PA-01 through PA-23 have been reviewed, PA-05 clarified as a defensive invariant test, and PA-07/PA-08 aligned with the locked per-number split exposure rule. The architecture and verification plan is documented at [Betting Engine Architecture and Test Plan](roulette/BETTING_ENGINE_ARCHITECTURE_AND_TEST_PLAN.md). The initial FastAPI foundation, smoke tests, and CI workflow are committed. The earlier owner-reported Python 3.14.4 verification block was resolved for this sandbox by testing with a temporary Python 3.12.12 environment on 2026-10-15: the complete 10-test suite, Ruff after five test-formatting corrections, and `/health/live` now pass. See [P01-T01 evidence](tasks/P01-T01.md). Next: obtain passing GitHub CI evidence for this branch; do not implement gameplay in this task.

## Verification artifacts

- [Canonical catalogue fixture](../../tests/fixtures/roulette_catalogue.json)
- [Catalogue fixture tests](../../tests/test_roulette_catalogue_fixture.py)
- [Cap and partial-acceptance edge cases](roulette/CAP_PARTIAL_ACCEPTANCE_EDGE_CASES.md)
- [Canonical legal-position catalogue](roulette/LEGAL_POSITION_CATALOGUE_REVIEW.md)
- [Betting engine architecture and test plan](roulette/BETTING_ENGINE_ARCHITECTURE_AND_TEST_PLAN.md)
- [P01-T01 — Python API foundation](tasks/P01-T01.md)

The catalogue tests validate catalogue invariants, not bet acceptance or settlement behavior. The new API is a liveness-only bootstrap; no betting-engine implementation has been written.

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
- Architecture and test plan recorded in `roulette/BETTING_ENGINE_ARCHITECTURE_AND_TEST_PLAN.md`.
- Local sandbox verification on 2026-10-15 using Python 3.12.12: editable install succeeded; 10/10 tests, Ruff and `/health/live` passed after test-formatting corrections. An upstream Starlette/httpx deprecation warning remains. Next action: observe the pull-request CI test/lint run and record its result before completing P01-T01. The owner's earlier Python 3.14.4 environment still needs a supported interpreter for their own local setup.
- No engine code exists yet; passing catalogue tests do not authorize treating cap or settlement behavior as verified.

## Do not do yet

Do not implement betting or payout code in P01-T01. First verify the foundation. Owner approval locks requirements; it does not waive verification gates.
