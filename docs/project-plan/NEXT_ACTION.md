# Next Action

## Active task

**P00-T02 — Execute catalogue fixture tests and verify cap/partial-acceptance criteria.**

## Objective

The owner approved the payout/settlement specification and canonical legal-position catalogue on 2026-10-14. A deterministic JSON fixture and standard-library Python tests have now been added. Next, execute the tests, record the result, then review the cap/partial-acceptance matrix against the approved requirements. Do not begin betting-engine implementation until these gates are cleared.

## Verification artifacts

- [Canonical catalogue fixture](../../tests/fixtures/roulette_catalogue.json)
- [Catalogue fixture tests](../../tests/test_roulette_catalogue_fixture.py)
- [Cap and partial-acceptance edge cases](roulette/CAP_PARTIAL_ACCEPTANCE_EDGE_CASES.md)
- [Canonical legal-position catalogue](roulette/LEGAL_POSITION_CATALOGUE_REVIEW.md)

The fixture/test files are specification verification artifacts only. The Python test suite has been committed but its execution result is not yet recorded. No betting-engine implementation is authorized by this step.

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
- Deterministic catalogue fixture and Python tests committed; test execution pending.
- Cap/partial-acceptance matrix is documented, but the acceptance behavior has not been implemented or verified against a running engine.
- Next: run python -m unittest discover -s tests -v, record the outcome, and review PA-01 through PA-23 for testability and consistency.
- Do not start betting-engine implementation until deterministic catalogue tests pass and the cap/concurrency/rollback/idempotency verification plan is complete.

## Do not do yet

Do not implement betting or payout code yet. Owner approval locks the requirements; it does not waive verification gates.
