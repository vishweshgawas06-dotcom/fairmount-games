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

- Hierarchy: one owner with global owner/admin management authority → agents → their assigned players; owner-created players may remain owner-managed without an agent. There are no sub-agents. Owner authority does not override audit, security, accepted-bet finality or independent RNG.
- No public self-registration; owner creates agents and may create players, agents may create only their assigned players. Agents cannot manage owner-managed or other agents' players.
- Player account starts at zero points and stores user ID, name, and mobile number; username/password login is required. Player usernames are globally unique across agents/owner-managed players, case-insensitive, 3–32 ASCII characters beginning with a letter and then letters/digits/underscore/hyphen. Reserve `admin`, `owner`, `support`, `system`, `root` and the `agt-` player prefix; username is fixed after creation in V1. Agent IDs are server-generated `AGT-` plus 10 unambiguous random uppercase letters/digits, unique in a separate namespace. Mobile numbers may be shared, stored as unverified contact data at registration and are not login authority. Username reuse after eligible anonymization remains undecided; see [D-11](decisions/2026-10-16-identifier-policy.md).
- Agents log in with Agent ID/password. Initial agent/player credential is server-generated, shown once to the authorized creator, expires after 24 hours if unused, and requires the recipient to set their own password on first activation. Owner can initiate secure password resets for agents/players; users/agents can change their own passwords. Passwords are never retrievable. See [P03-T01a contract](auth/REGISTRATION_IDENTIFIER_CONTRACT.md); no registration/authentication implementation exists yet.
- Owner can create/manage agents and users, adjust points with required reasons, disable/enable accounts, and inspect system records.
- Agents can manage only their enabled, currently assigned players and cannot transfer more points than their agent-wallet balance. Their dashboard lists assigned enabled players whether online or offline.
- Player cannot see overall profit/loss or administrative transaction history.
- One active session per account for owner, agents and players; a new login invalidates the older session. Server-enforced idle/absolute expiry: owner 15 minutes/8 hours; agent 30 minutes/12 hours; player 30 minutes/24 hours. Disablement, password reset/change and owner MFA recovery revoke all affected sessions. See [D-03](decisions/2026-10-16-owner-mfa-and-sessions.md).
- Reconnection must recover authoritative server state. A server-accepted bet remains valid; a bet not accepted by the server does not exist.
- Passwords must never be retrievable in plaintext; use secure password hashing and reset flows.

## Bet acceptance and insufficient balance

- If a player's wallet balance is below an ordinary requested bet stake, reject the entire bet and preserve the balance unchanged. Do not accept a balance-limited partial stake.
- Partial acceptance is allowed for cap-limited bets only when the player can cover the full requested stake; accept the largest valid amount within applicable caps and return the cap-excess atomically, subject to chip/minimum rules.

## Accounting

- Maintain an auditable point ledger. Owner-only, reasoned issuance creates virtual points in the owner wallet; owner↔agent and owner↔player additions/removals and agent↔assigned-player additions/removals are atomic linked transfers between existing wallets. If the source cannot cover the full requested transfer, reject it entirely. The owner can transfer directly to any player. See [D-10](decisions/2026-10-15-account-provisioning-and-point-flow.md).
- A separately owner-funded game reserve pays winning total returns and void refunds. [POOL-01](decisions/2026-10-19-funded-reserve-solvency.md) approves prospective admission only when, after the candidate stake moves into the reserve, its balance covers the sum across unsettled rounds of the greater of full void refunds or the highest total payout among all 37 numbers. Reject an underfunded *new* bet entirely; never alter or withhold an accepted one. Concurrency/ledger design, funding operations and incident handling remain unimplemented. Transfers conserve points; issuance and gameplay must be distinctly accounted for.
- Separate gameplay wins/losses from administrative allocations/adjustments.
- Gameplay P/L = winnings minus losses, under the approved payout convention.
- Every administrative point adjustment requires a reason and an audit record.

## User experience

- Premium original casino-inspired interface, deep green table and restrained gold accents.
- Desktop and mobile support; mobile has a dedicated landscape layout with safe-area and viewport handling.
- Realistic-feeling European roulette machine: smoothly spinning wheel and ball with believable motion and landing, while visually landing on the server-provided result; animation must never determine the result. Owner reconfirmed the realistic-feel goal on 2026-10-15. Specific visual references, target-device performance thresholds, and reduced-motion presentation remain design review items.
- Show balance, individual bets, winning numbers, and current-session game history to players.
- Sound effects for wheel, ball, chips, buttons, and result; no background music/ambience; separate volume controls.
- No hidden or unusable controls at supported viewport sizes.

## Security and reliability

- Server validates every bet, balance change, role permission, and round transition.
- Use transactional accounting, idempotency, database constraints, rate limits, structured logs, and audit trails.
- Owner MFA is required before production: TOTP authenticator plus single-use offline recovery codes; require MFA checked within 10 minutes for sensitive owner actions. If all factors and codes are lost, no self-service bypass; a separate manual recovery procedure still needs approval.
- Secure cookies, HTTPS, strict CORS, secret management, and security testing are required.
- Client is untrusted; hiding UI controls is not authorization.
- Realtime messages must not permit users to forge balances, outcomes, or accepted bets.

## Roulette payout/settlement rules approved 2026-10-14

The owner approved the P00-T02 payout/settlement specification on 2026-10-14. See [approved payout and settlement specification](roulette/PAYOUT_AND_SETTLEMENT_SPEC_DRAFT.md) for exact payout multipliers, caps, accepted-bet finality, rebet, settlement, zero handling, and failure recovery. The canonical legal-position catalogue was owner-approved on 2026-10-14. A deterministic fixture and specification-only Python tests have been added under tests/. The owner reported the catalogue suite passing locally on 2026-10-14 (8 tests, 0 failures). PA-01–PA-23 have been reviewed; PA-05 is a defensive invariant test for an invalid state unreachable through valid multiples-of-5 operations. Split bets are constrained by the 2,000-coin exposure cap on each constituent number; the locked requirements do not specify a separate exact-split cap. Actual cap/partial-acceptance, concurrency, transaction, idempotency, settlement/refund, and player-privacy behavior remain unimplemented and must be tested against the engine before production.

## Account removal and personal-data handling approved 2026-10-15

See [D-01 account disablement/reassignment](decisions/2026-10-15-account-disable-and-reassignment.md) and [D-02 privacy deletion/retention](decisions/2026-10-15-privacy-deletion-and-retention.md). Ordinary player/agent removal disables access and new actions; existing accepted player bets still settle or void/refund under the approved global policy. Disabled player balances remain frozen after settlement (not automatically reclaimed or forfeited). The owner may immediately reassign a disabled agent's players with audited, atomic authorization changes; unused agent allocation must be reconciled back to the owner through auditable budget/ledger entries without rewriting history. Eligible verified personal-data deletion is separate: anonymize identifying details when permitted while retaining non-identifying accounting records. These policies are approved but **not implemented**.

## Unresolved

Do not guess exact historical-record retention periods, deletion eligibility/exceptions, backup lifecycle, username/Agent-ID reuse after anonymization or jurisdiction-specific legal requirements; D-02/D-11 remain partially open and destructive cleanup is blocked. D-03 now locks baseline MFA/timeouts/step-up/revocation and one active session for every role, but a manual all-factors-lost owner recovery process is undecided. Operational SLOs/performance targets remain open. The owner approved the POOL-01 funded-reserve pre-bet coverage/global acceptance policy on 2026-10-19, but transactional implementation and failure/operations review remain open. The cap/partial-acceptance behavior remains unimplemented and unverified. Catalogue fixture tests do not establish engine behavior.
