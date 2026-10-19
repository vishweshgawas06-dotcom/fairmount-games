# FairMount Games — Master Plan

## Delivery rule

Work in small, verifiable tasks. Each task must identify its scope, acceptance criteria, tests/evidence, and documentation updates. Do not begin implementation when a blocking product decision is unresolved.

For task-sized work, dependencies, decision checkpoints, and verification gates across all phases, see [Detailed delivery plan](DETAILED_DELIVERY_PLAN.md). The owner approved the delivery sequence on 2026-10-15; this is not blanket approval to implement individual tasks. Approved product rules remain in [Locked Requirements](LOCKED_REQUIREMENTS.md) and the owner-approved roulette specifications.

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
- Betting is open during seconds 0–44; show the final-bet call at second 45 while bets remain open; server closes/freezes accepted bets and begins wheel/ball animation at second 50; reveal the persisted result and settle at second 60. See the owner-approved payout/settlement specification. Implementation-level clock and recovery details still need design review.
- Chip denominations: 5, 10, 50, 100, 500 virtual points.
- Outcome generation must not depend on bets or player balances.
- Gameplay P/L is separate from administrative point adjustments.
- No real-money functions in V1.

## Release discipline

A phase is not complete because code exists. It is complete only when acceptance criteria pass, relevant tests run, failures are documented, and the task/status documents are updated.
