# Locked Requirements

This document records current requirements. Items explicitly listed as unresolved must not be guessed by implementation.

## Product scope

- Product: FairMount Games; V1 game: FairMount Roulette.
- V1 uses virtual points only. Real-money wagering and payment functionality are excluded.
- One game in V1; keep architecture extensible without building unrelated games.

## Roulette and rounds

- Single-zero European wheel, numbers 0–36.
- A server-authoritative global round and one outcome shared by all active players.
- Outcome generation is independent of stakes, bets, balances, and player identity.
- Nominal round duration: 60 seconds.
- Betting is accepted during seconds 0–49 and closed from second 50.
- Seconds 50–59 are the result/settlement phase; exact ordering of animation, result publication, and settlement is still unresolved.
- Chip values: 5, 10, 50, 100, 500.
- Multiple bets per round.
- Unlimited rounds while the player has sufficient points to place a valid bet.

## Roles and account management

- Hierarchy: Owner/Admin → Agent → Player.
- No public self-registration; accounts are created by authorized owner/admin or agent.
- Player account starts at zero points and stores user ID, name, and mobile number.
- Owner can create/manage agents and users, adjust points with required reasons, disable/enable accounts, and inspect system records.
- Agents can manage only their own users and cannot exceed their allocated point budget.
- Player cannot see overall profit/loss or administrative transaction history.
- One active player session per account; a new login may invalidate the older session.
- Reconnection must recover authoritative server state. A server-accepted bet remains valid; a bet not accepted by the server does not exist.
- Passwords must never be retrievable in plaintext; use secure password hashing and reset flows.

## Accounting

- Maintain an auditable point ledger.
- Separate gameplay wins/losses from administrative allocations/adjustments.
- Gameplay P/L = winnings minus losses, under the approved payout convention.
- Every administrative point adjustment requires a reason and an audit record.

## User experience

- Premium original casino-inspired interface, deep green table and restrained gold accents.
- Desktop and mobile support; mobile has a dedicated landscape layout with safe-area and viewport handling.
- Smooth wheel/ball animation that visually lands on the server-provided result; animation must never determine the result.
- Show balance, individual bets, winning numbers, and current-session game history to players.
- Sound effects for wheel, ball, chips, buttons, and result; no background music/ambience; separate volume controls.
- No hidden or unusable controls at supported viewport sizes.

## Security and reliability

- Server validates every bet, balance change, role permission, and round transition.
- Use transactional accounting, idempotency, database constraints, rate limits, structured logs, and audit trails.
- Owner/admin MFA is required before production.
- Secure cookies, HTTPS, strict CORS, secret management, and security testing are required.
- Client is untrusted; hiding UI controls is not authorization.
- Realtime messages must not permit users to forge balances, outcomes, or accepted bets.

## Unresolved

Do not treat these as locked until explicitly approved: exact bet catalogue/payouts; animation and settlement timing; delete/deactivate/anonymize semantics; history retention; owner MFA recovery; operational SLOs and performance targets.
