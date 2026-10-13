# Repository Bootstrap Checklist

This repository is in the specification phase. Do not start application implementation until the active P00 blocking decisions are approved.

## Current first steps

- [x] Verify GitHub repository access and default branch.
- [x] Add project overview, security baseline, locked requirements, master plan, and task tracking.
- [ ] Approve roulette bet catalogue and payout convention (P00-T02).
- [ ] Approve remaining timing, retention/deletion, session recovery, and operational targets.
- [ ] Add reproducible local development and CI tooling in P01.
- [ ] Confirm a clean clone and document tested setup commands.

## Repository hygiene

- Keep .env files and credentials out of Git.
- Use .env.example only for variable names and safe placeholders.
- Make small commits with clear messages.
- Never claim a test or deployment was verified unless it was actually run.
