# D-10 — Account provisioning, wallet transfers and game reserve

**Status:** Owner-approved product flow on 2026-10-15; game-reserve capacity formula, sizing and operations remain proposed/unapproved. No implementation authorized by this decision.

## Context and alternatives

The owner confirmed the Owner → Agent → Player management model and clarified how virtual points are issued, transferred and returned. Alternatives discussed: agent allocation as a permission ceiling, issuing points directly into any target wallet without an owner debit, allowing partial/negative-balance removals, and letting agents create sub-agents. Those alternatives were **not** selected. A fixed stock of owner points was not selected; owner-only auditable issuance into the owner wallet was selected instead. For game winnings, owner selected a separately funded game reserve over untracked payout issuance; exact pre-bet solvency rule still needs approval.

## Approved account and authority flow

1. V1 has **one owner account**, held by the owner, with authorized management access to all agents and players. This does not permit viewing plaintext passwords, bypassing audit, manipulating RNG, altering accepted bets or ignoring MFA/security controls. Owner succession/recovery and MFA policy remain separate decisions (D-03); do not claim absolute account recovery guarantees.
2. Owner creates agents with registered details and a unique Agent ID. The agent receives initial login credentials, can change their password, and authenticates to the agent dashboard by Agent ID and password. Owner can reset agent or player passwords when forgotten. Owner can also create players directly; such players may remain **owner-managed with no agent assignment**.
3. An agent may create only player accounts, with a username and initial password. Those players are assigned to that agent, log in with their username/password and may change their passwords. No agent-created sub-agents; no public self-registration. Player data also includes the approved identity fields (name/mobile and ID). Owners/agents need not know a wallet holder's password to perform an *authorized* wallet transfer later.
4. Agent dashboard shows the agent's **enabled, currently assigned** players whether online or offline. No visibility or management of another agent's players or owner-managed players. Owner dashboard has all authorized agents and players. Current assignment may change under D-01; historical actor/agent attribution must not be rewritten.
5. Users and agents may discuss registration and point requests by mobile or WhatsApp **outside** the product. V1 has no WhatsApp integration or authority delegated to a chat message. Actual account and wallet actions occur after authenticated dashboard authorization, with server validation and audit. Do not transmit/reset reusable plaintext passwords in routine chat; the [P03-T01a registration contract](../auth/REGISTRATION_IDENTIFIER_CONTRACT.md) records the owner-approved, single-use 24-hour temporary activation approach, not an implemented feature.

## Approved point flow

- **Issuance:** only an authorized owner action creates virtual points into the owner wallet, with required amount, reason, actor, timestamp and immutable audit/ledger evidence. Issuance is the only administrative source of new points. It is not described as a transfer.
- **Owner add/remove:** entering points for an agent or player transfers available points from owner wallet to that target; an owner removal transfers available points back to owner wallet. Owner can transfer directly to any player, including a player assigned to an agent. Every transfer debits source and credits destination atomically with linked entries, reason, actor and idempotency reference. Never silently mint points directly in the target wallet when using the add control.
- **Agent add/remove:** an agent transfers points only between the agent wallet and currently assigned player wallets. Addition debits agent and credits player; removal requested by the player debits player and credits that agent. The agent must not operate on another agent's or an owner-managed player. A chat request alone is not authentication or proof of authorization for the server.
- **Insufficient balance:** if source wallet has fewer available points than the **full requested transfer**, reject the entire operation with neither wallet changed; no negative balance or balance-limited partial transfer. Already-accepted bet stakes have been debited and cannot be taken again.
- **Disablement:** normal removals from disabled players remain blocked; their wallet stays frozen for initiated transfers, while accepted bets still settle/refund. D-01 governs agent disable/reassignment and unused agent-budget return to owner with historical audit preserved.
- **Conservation:** owner↔agent, owner↔player, agent↔assigned-player, and owner→game-reserve funding are movements of existing points. Issuance is explicitly recorded as an increase in total virtual supply; do not equate transfer with issuance. Gameplay stakes/payout/refunds need traceable game-pool counterparts to reconcile the system.

### Example (administrative transfers only)

Owner wallet 10,000 → transfer 3,000 to agent B: owner 7,000; B 3,000. B transfers 500 to assigned player C: B 2,500; C 500. On a later eligible 100-point return requested by C, agent 2,600; C 400. A direct owner removal from C would credit the **owner**, not B. These examples assume no gameplay between actions and no issuance after the starting balance.

## Game reserve: approved direction, details still open

Owner selected an **owner-funded game/house point pool** to pay roulette wins without manipulating results or withholding accepted winnings. Conceptually: fund pool by an audited owner-wallet transfer, move accepted stakes into it, pay winning total returns from it, and return voided stakes from it. Before accepting a new bet, assess whether the pool can honor **every possible** outcome of all accepted bets, including the proposed bet and all winning bet types across active players; otherwise reject the new bet under a disclosed prospective rule. This is a *design candidate*, not a final numerical cap, algorithm or existing product constraint. The exact coverage calculation, reserve timing, replenishment policy, response to insufficiency, lock strategy and owner approval of any global acceptance limit are **open**. Never change an outcome based on exposure, revoke an accepted bet, withhold a valid payout or silently issue points to hide a deficit.

## Security and accounting implications

- Hash passwords with Argon2id; restrict raw credentials to one-time delivery and secure reset flows. Privileged actions require owner MFA before production, session checks, per-resource authorization, rate limits, reason/audit and replay-safe idempotency. Design temporary agent/player credentials and forced changes without storing plaintext or exposing hashes.
- Ledger transfers should record paired debit/credit effects with one transfer ID and preserve global conservation apart from explicit issuance. Each wallet projection reconciles to its own immutable ledger; no manual balance edits. Make concurrent transfer and agent reassignment tests mandatory.
- Do not use mobile/WhatsApp requests as a substitute for authenticated operator authority. Capture minimal request/consent context in the audit without copying full chats or personal details into general logs.
- The game pool and worst-case exposure check require atomic accounting alongside bet acceptance and cutoff; PostgreSQL is the source of truth. A global reserve/limit may change bet-acceptance behavior and therefore needs a separate explicit owner decision before implementation.

## Follow-up gates

- P02-T01: update conceptual wallet/account/session/agent-assignment and game-pool sketch; keep exact reserve policy unapproved. Owner review of entire conceptual schema is still pending.
- P03/P04: specify unique IDs/usernames, secure invitation/reset process, MFA (D-03), single-player session, and owner/agent scope tests. Owner-managed players must not appear in agent views.
- P05: design paired transfers, issuance journal, game pool, cross-wallet reconciliation and source-of-points accounting. Test insufficient full-request rejection and D-01 frozen-wallet exceptions on PostgreSQL.
- P08/P11: approve and test the pre-bet reserve coverage rule under multi-player concurrency and all 37 potential results **before** coding a global acceptance restriction. Existing 2,000 per-player/selection caps remain unchanged unless separately approved.
- P17/P18: measure reserve checks and settle scale, define alerts/funding runbooks, disclose game rules, and review virtual-point/privacy/legal obligations. No claim of financial/legal certification.
