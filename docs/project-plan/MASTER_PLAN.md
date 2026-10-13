# FairMount Games — Master Plan

## Delivery rule

Work in small, verifiable tasks. Each task must identify its scope, acceptance criteria, tests/evidence, and documentation updates. Do not begin implementation when a blocking product decision is unresolved.

## Phases

| Phase | Focus | Gate |
|---|---|---|
| P00 | Specification lock | Required rules and edge cases approved |
| P01 | Repository foundation | Reproducible local setup and CI baseline |
| P02 | Database and migrations | Schema, constraints, and migration workflow reviewed |
| P03 | Authentication and sessions | Secure login, logout, recovery, session policy |
| P04 | Authorization | Owner/agent/player boundaries tested server-side |
| P05 | Wallet and ledger | Atomic, auditable point accounting |
| P06 | Owner dashboard | Administrative operations and audit trail |
| P07 | Agent dashboard | Agent-scoped user management and allocation limits |
| P08 | Roulette engine | Deterministic round state machine and approved payout rules |
| P09 | Realtime delivery | Shared authoritative round state and reconnect behavior |
| P10 | Player interface | Responsive table, balance, history, and round state |
| P11 | Betting controls | Bet placement, validation, limits, and settlement |
| P12 | 3D roulette | Smooth, deterministic visual landing on the server result |
| P13 | Audio and settings | User-controlled effects and persistence policy |
| P14 | UI and responsiveness | Desktop/mobile landscape and accessibility review |
| P15 | Reliability | Disconnects, retries, duplicate requests, and recovery |
| P16 | Testing and security | Unit/integration/E2E/security gates |
| P17 | Performance | Measured load and latency targets approved and tested |
| P18 | Staging and acceptance | End-to-end acceptance and rollback rehearsal |
| P19 | Production launch | Operational readiness and explicit release approval |

## Architecture target

- Three web surfaces: player, agent, admin.
- FastAPI backend, PostgreSQL persistence, SQLAlchemy 2, Alembic migrations.
- WebSockets for realtime state; Redis only where its coordination role is explicitly designed.
- Docker-based local development and CI checks with Pytest and Playwright.
- Shared contracts/types validated across client and server.

## Core gameplay constraints

- European roulette: one zero, numbers 0–36.
- One server-generated result per global round, shared by active players.
- Betting is open from second 0 through second 49; betting closes at second 50. Seconds 50–59 are the result/settlement phase. Exact animation and settlement sequencing remains a decision to lock.
- Chip denominations: 5, 10, 50, 100, 500 virtual points.
- Outcome generation must not depend on bets or player balances.
- Gameplay P/L is separate from administrative point adjustments.
- No real-money functions in V1.

## Release discipline

A phase is not complete because code exists. It is complete only when acceptance criteria pass, relevant tests run, failures are documented, and the task/status documents are updated.
