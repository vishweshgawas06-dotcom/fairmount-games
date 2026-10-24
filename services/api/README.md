# FairMount Games API

FastAPI liveness foundation only. P02-T02a introduces an account/identity/assignment **database schema** and local Alembic runner, but the API has no database session, login, authorization, gameplay or betting routes. `/health/live` remains process liveness, not database readiness.

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

Check <http://127.0.0.1:8000/health/live>. It reports process liveness only and does not check database readiness.

Run tests and lint:

```powershell
python -m unittest discover -s tests -v
ruff check .
```

The current health endpoint is not evidence of a deployed game. UUID wallet/reserve, private bet/settlement/recovery transactions and PostgreSQL tests have since been added, but there are **no public login, betting, reveal or payout routes**. P03/P04 edge security and broader D-06 operations still gate deployment.

## Opt-in round worker (not deployed)

The private `fairmount_api.roulette.worker` entry point polls migrated PostgreSQL for due rounds, commits result persistence separately from settlement, and retries a missing independent result after cutoff under [D-06a](../../docs/project-plan/decisions/2026-10-24-round-result-recovery.md). It never automatically voids or rerolls a persisted result. It is **not** started by FastAPI. A supervised deployment must supply `FAIRMOUNT_WORKER_DATABASE_URL` (`postgresql+psycopg://...`) from protected configuration outside Git and launch `python -m fairmount_api.roulette.worker`; never put a URL or credentials in a command argument, log or repository file. Configure real alerts and secret rotation before production. A process restart alone is not a complete operations runbook.
