# FairMount Games API

FastAPI health and public read-only round snapshot foundation. P02-T02a introduced an account/identity/assignment **database schema** and local Alembic runner, but the API has no login, authorized wallet, wagering or payout routes. `/health/live` is process liveness; `/health/ready` checks a separately configured PostgreSQL URL and exact migration revision, not worker or game availability.

## Planned module boundaries

- `auth/` — authentication and session lifecycle
- `users/` and `agents/` — account and hierarchy management
- `wallets/` and `transactions/` — point ledger and accounting
- `roulette/` and `bets/` — round state, bet validation, outcomes, settlement
- `realtime/` — authorized WebSocket state updates
- `audit/` and `security/` — audit events and security controls

## Local development

Run commands from the repository root. Python 3.12 or 3.13 is required.

Install dependencies:

```powershell
python -m pip install -e ".[dev]"
```

Start the API:

```powershell
uvicorn fairmount_api.main:app --reload --app-dir services/api/src
```

Check <http://127.0.0.1:8000/health/live> for process liveness. `/health/ready` returns HTTP 503 unless `FAIRMOUNT_API_DATABASE_URL` is explicitly supplied outside Git as a `postgresql+psycopg://` URL for a migrated database; it requires Alembic revision `20261023_03`. Restart the API after changing this URL. Readiness responses never contain connection details and are not cached. Neither health endpoint checks the round worker, reserve coverage or whether gameplay is publicly available; do not route players to this preview as a working game.

Run tests and lint:

```powershell
python -m unittest discover -s tests -v
ruff check .
```

The read-only `/api/v1/roulette/round` endpoint and `/preview/` interface can show a persisted server result **only after reveal** when a migrated database and separately started worker exist. The preview has no fake result if no database is configured. This is not evidence of a deployed game. UUID wallet/reserve and private bet/settlement/recovery transactions have PostgreSQL tests, but there are **no public login, betting, transfer or payout routes**. P03/P04 edge security and broader D-06 operations still gate deployment.

## Opt-in round worker (not deployed)

The private `fairmount_api.roulette.worker` entry point polls migrated PostgreSQL for due rounds, commits result persistence separately from settlement, and retries a missing independent result after cutoff under [D-06a](../../docs/project-plan/decisions/2026-10-24-round-result-recovery.md). It never automatically voids or rerolls a persisted result. It is **not** started by FastAPI. A supervised deployment must supply `FAIRMOUNT_WORKER_DATABASE_URL` (`postgresql+psycopg://...`) from protected configuration outside Git and launch `python -m fairmount_api.roulette.worker`; never put a URL or credentials in a command argument, log or repository file. Configure real alerts and secret rotation before production. A process restart alone is not a complete operations runbook.

For read-only operator observation, `python -m fairmount_api.roulette.worker_status_cli` uses the **same protected worker URL** and reports due OPEN/CLOSED transition counts and the oldest due timestamp as JSON. An unavailable DB/schema yields a generic exit-code-2 error without printing credentials. Due counts do not change the exit code: the owner has not approved a lag/SLO threshold. This is neither a heartbeat nor a recovery action, and must not be used to void a round or patch wallet balances.
