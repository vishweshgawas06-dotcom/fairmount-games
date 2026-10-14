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
- Betting is open during seconds 0–44; at second 45 show the final-bet call while betting remains open; close and freeze accepted bets at second 50. At second 50, begin wheel/ball animation; at second 60, reveal the result and settle.
- The animation must land on the server-determined outcome and must never determine the outcome.
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

## Bet acceptance and insufficient balance

- If a player's wallet balance is below an ordinary requested bet stake, reject the entire bet and preserve the balance unchanged. Do not accept a balance-limited partial stake.
- Partial acceptance is allowed for cap-limited bets only when the player can cover the full requested stake; accept the largest valid amount within applicable caps and return the cap-excess atomically, subject to chip/minimum rules.

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

## Roulette payout/settlement rules approved 2026-10-14

The owner approved the P00-T02 payout/settlement specification on 2026-10-14. See [approved payout and settlement specification](roulette/PAYOUT_AND_SETTLEMENT_SPEC_DRAFT.md) for exact payout multipliers, caps, accepted-bet finality, rebet, settlement, zero handling, and failure recovery. The canonical legal-position catalogue was owner-approved on 2026-10-14. Its deterministic counts/red-black fixtures and cap/partial-acceptance acceptance tests remain pre-implementation verification gates.

## Unresolved

Do not guess these: delete/deactivate/anonymize semantics; history retention; owner MFA recovery; operational SLOs and performance targets; and verified cap/partial-acceptance behavior. The canonical legal-position catalogue itself is owner-approved; automated verification remains required.
