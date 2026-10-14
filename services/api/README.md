# FairMount Games API

Initial FastAPI foundation only. Gameplay, authentication, database connectivity, and betting logic are not implemented in this task.

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

The current health endpoint is not evidence that gameplay or persistence is implemented. Do not add payout logic until the P00 requirements and test gates are satisfied.
