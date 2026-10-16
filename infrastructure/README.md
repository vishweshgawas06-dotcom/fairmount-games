# Local PostgreSQL foundation (P01-T03)

This is a **local-only** PostgreSQL 16 development/test service, not a deployed database or game schema. The API's `/health/live` remains process liveness and does **not** check PostgreSQL. No tables, migrations, wallet or betting logic are created here. Redis and production deployment are not configured.

## Requirements

- Docker Engine/Desktop with Docker Compose v2 (`docker compose version`).
- Python 3.12 or 3.13 and an isolated virtual environment; run all commands from the repository root.
- Free localhost port 5432, or change `POSTGRES_PORT` in `.env`.

## Clean setup (macOS/Linux shell)

```sh
cp .env.example .env
# Edit .env: replace POSTGRES_PASSWORD with a unique local-only password.
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
docker compose --env-file .env -f infrastructure/compose.yaml up -d --wait
python infrastructure/check_postgres.py
python -m unittest discover -s tests -v
python -m ruff check .
```

On Windows PowerShell, use `Copy-Item .env.example .env`, edit `.env`, `py -3.12 -m venv .venv`, `.\.venv\Scripts\Activate.ps1`, then the same `python`, `docker compose` and test commands. Python 3.13 also satisfies the project requirement. Never commit `.env`; the sample credentials are placeholders for local use only. `DATABASE_URL` in `.env` is a **future API placeholder**, not used by this check; if you change the local password, keep that URL consistent for later API work.

Compose publishes PostgreSQL to **127.0.0.1 only** and stores data in a named Docker volume. `fairmount_dev` is the development database. The check script connects to that database, creates `fairmount_test` **if missing**, and connects to it to run `SELECT current_database(), 1`. It refuses other database names, uses only localhost, and never drops a database or adds application tables. The smoke check does not establish readiness of the gameplay service or verify the schema.

## P02-T02a account-schema migration (separate, owner-approved slice)

After the isolated test database check succeeds, you may apply the **first account-only migration** to the test database:

```sh
# macOS/Linux; run with the project virtual environment active:
FAIRMOUNT_DB_NAME=fairmount_test python -m alembic upgrade head
FAIRMOUNT_DB_NAME=fairmount_test FAIRMOUNT_RUN_DB_TESTS=1 python -m unittest discover -s tests -v
FAIRMOUNT_DB_NAME=fairmount_test python -m alembic check
```

On PowerShell set `$env:FAIRMOUNT_DB_NAME='fairmount_test'` and `$env:FAIRMOUNT_RUN_DB_TESTS='1'` in that shell before running the same `python -m alembic ...` and `python -m unittest ...` commands. For a fresh local development database, omit `FAIRMOUNT_DB_NAME` (defaults to `fairmount_dev`) and run `python -m alembic upgrade head`; **do not downgrade a database whose data you need**. CI alone runs `upgrade head → downgrade base → upgrade head` against its disposable `fairmount_test` database. Downgrade drops account tables and their data. See [P02-T02a boundaries](../docs/project-plan/tasks/P02-T02a.md): these tables do not provide login, wallet, betting or privacy-deletion behavior yet.

## Stop or reset

```sh
# Stop containers, keep your local development/test databases:
docker compose --env-file .env -f infrastructure/compose.yaml down

# Destructive reset of this local Compose project's databases ONLY:
docker compose --env-file .env -f infrastructure/compose.yaml down --volumes
```

`down --volumes` **deletes both local development and test data**. Do not run it against a production environment or while you need your local data. To restart without deleting data, run `up -d --wait` again. Changing `POSTGRES_USER`, `POSTGRES_PASSWORD` or `POSTGRES_DB` in `.env` after initial volume creation will **not** reinitialize an existing PostgreSQL volume; plan a local reset or an explicit database administration step instead.

## CI and limitations

The pull-request workflow checks out a clean repository, starts this Compose service with temporary example values, runs the same isolated test-database connection check, then runs the Python tests and Ruff. It removes its ephemeral CI volume afterward. This sandbox may not have Docker; in that case CI is the verification evidence for Compose and local Docker commands remain unverified here. Later phases must add PostgreSQL schema migrations and real transaction/concurrency tests under separate permission.
