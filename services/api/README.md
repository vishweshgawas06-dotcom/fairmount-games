# API Service

Planned FastAPI backend. The server is authoritative for identity, authorization, balances, bets, round state, outcomes, settlement, and audit records.

## Planned module boundaries

- auth/ — authentication and session lifecycle
- users/ and agents/ — account and hierarchy management
- wallets/ and transactions/ — point ledger and accounting
- roulette/ and bets/ — round state, bet validation, outcomes, settlement
- realtime/ — authorized WebSocket state updates
- audit/ and security/ — audit events and security controls

Status: not implemented. Do not add payout logic until P00-T02 is approved.
