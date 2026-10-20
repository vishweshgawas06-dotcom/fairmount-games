# Next Action

## Active task

**P01-T01 close-out, then owner review of the engine core (added 2026-10-20) before starting P03 authentication.**

## Objective

1. Create a Python 3.13 virtual environment (`py -0p`, then `py -3.13 -m venv .venv`), activate it, and install with `python -m pip install -e ".[dev]"`.
2. Start a local PostgreSQL test database (for example `docker compose up -d test-db`, unverified) and set `FAIRMOUNT_TEST_DATABASE_URL=postgresql+psycopg://fairmount:fairmount@localhost:5433/fairmount_test` and `FAIRMOUNT_REQUIRE_DB=1`.
3. Run `python -m ruff check .` and `python -m pytest -q`. Expected from the independent run: Ruff clean and 233 passed. Record the owner's actual results here.
4. Run migrations on a dev database: set `DATABASE_URL`, then from `services/api` run `alembic upgrade head`.
5. Confirm the two owner decisions listed under "Assumptions and open items" in PROJECT_STATUS.md (per-player number cap; payout convention).
6. Check the GitHub Actions run on the first push; it now needs the PostgreSQL service defined in the workflow.

Do not expose any engine function over HTTP until P03/P04 authentication and authorization exist.

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
- Engine core exists and is verified only in an independent sandbox (233 tests); treat it as unverified until the owner records local and GitHub Actions results.

## Do not do yet

Do not build HTTP betting endpoints, realtime, or UI before authentication and authorization. Owner approval locks requirements; it does not waive verification gates.
