# FairMount Games

FairMount Games is a planned, responsive virtual-points gaming platform. Version 1 focuses on a single-zero European roulette experience using **virtual points only**.

## Current status

**Implementation in progress; not production-ready.** Server-authoritative UUID
wallet/reserve, roulette and protected identity/point services have scoped test
evidence. The shared owner/agent console now lives at `/console/`; the public
reveal-only roulette preview remains at `/preview/`. Privileged APIs deliberately
remain unavailable in the ordinary proxy preview. No real-money functionality or
production acceptance is claimed. See the [current status](docs/project-plan/PROJECT_STATUS.md),
[next action](docs/project-plan/NEXT_ACTION.md) and [console checkpoint](docs/project-plan/tasks/P06-T02a.md).

## Product principles

- One server-authoritative roulette round and result shared by all active players.
- European roulette numbers 0–36 with a single zero.
- Results generated independently of player bets; never manipulate outcomes to reduce payouts.
- Virtual points only in V1; no deposits, withdrawals, cash prizes, or real-money wagering.
- Owner → Agent → Player hierarchy with server-enforced resource-level authorization.
- Auditable point movements, with gameplay profit/loss kept separate from administrative adjustments.
- Responsive player experience, with a dedicated mobile landscape layout.
- Security, recoverability, accessibility, and transparent error handling are requirements, not post-launch extras.

## Intended architecture

- **Browser UI:** incremental ES-module operator console and read-only roulette preview; Next.js/TypeScript/React/Tailwind remain proposed full-app choices.
- **API:** FastAPI, Python, SQLAlchemy 2, Alembic.
- **Data:** PostgreSQL; Redis for appropriate coordination/caching needs.
- **Realtime:** public reveal-safe SSE exists; private event delivery remains open.
- **Testing/operations:** Pytest, Playwright, Docker, GitHub Actions, Sentry.

Architecture choices are not completion evidence; consult the task records for tested scope and remaining gates.

## Repository map

- `apps/player-web/` — player-facing web client
- `apps/agent-web/` — agent console
- `apps/admin-web/` — owner/admin console
- `services/api/` — FastAPI service
- `packages/` — shared UI, contracts, and utilities
- `infrastructure/` — local infrastructure and deployment configuration
- `docs/project-plan/` — requirements, decisions, phases, and task plans

## Start here

1. Read [locked requirements](docs/project-plan/LOCKED_REQUIREMENTS.md).
2. Read [master plan](docs/project-plan/MASTER_PLAN.md).
3. Follow [next action](docs/project-plan/NEXT_ACTION.md).
4. Complete unresolved specification decisions before implementing the roulette betting engine.

## Development rules

- Treat all client input as untrusted.
- Enforce authorization in the API and data access layer, not only in the UI.
- Use database transactions and idempotency for wallet and bet operations.
- Never store plaintext passwords or expose password hashes.
- Record architectural decisions and meaningful administrative actions.
- Make small, reviewable changes and run relevant tests before claiming completion.
- Do not introduce real-money functionality into V1.

See [SECURITY.md](SECURITY.md) and [workflow rules](docs/project-plan/WORKFLOW_AND_UPDATE_RULES.md).
