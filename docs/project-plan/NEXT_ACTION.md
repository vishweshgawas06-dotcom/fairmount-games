# Next Action

## Active task

**P01-T01 — Unblock and verify the initial Python API foundation locally.**

## Objective

The owner-approved roulette specification and catalogue fixture gates are recorded. The owner reported 8/8 catalogue tests passing locally. PA-01 through PA-23 have been reviewed, PA-05 clarified as a defensive invariant test, and PA-07/PA-08 aligned with the locked per-number split exposure rule. The architecture and verification plan is documented at [Betting Engine Architecture and Test Plan](roulette/BETTING_ENGINE_ARCHITECTURE_AND_TEST_PLAN.md). The initial FastAPI foundation, smoke tests, and CI workflow are committed. On 2026-10-15, the owner reported that installation was rejected because the active Python is 3.14.4 but the project requires `>=3.12,<3.14`; the catalogue tests passed 8/8, while the API test could not import FastAPI and Ruff/Uvicorn were unavailable. First inspect installed Python versions with `py -0p`, then use Python 3.13 in a virtual environment (install Python 3.13 if absent), install dependencies, and rerun tests/lint/liveness. Do not implement gameplay in this task.

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
- Active next action: run `py -0p`; create and activate `.venv` using Python 3.13; install with `python -m pip install -e ".[dev]"`; run `python -m unittest discover -s tests -v` and `python -m ruff check .`; start Uvicorn with `python -m uvicorn fairmount_api.main:app --reload --app-dir services/api/src` and check `/health/live`. The 2026-10-15 attempt is blocked by Python 3.14.4 and missing uninstalled dependencies; only the 8 catalogue tests passed.
- No engine code exists yet; passing catalogue tests do not authorize treating cap or settlement behavior as verified.

## Do not do yet

Do not implement betting or payout code in P01-T01. First verify the foundation. Owner approval locks requirements; it does not waive verification gates.
