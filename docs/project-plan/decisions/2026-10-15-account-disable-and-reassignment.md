# D-01 — Account disablement, reassignment and point accounting

**Status:** Accepted by owner on 2026-10-15 for V1 product behavior; implementation and verification not started.

## Context

The Owner → Agent → Player hierarchy has server-owned sessions, point balances, accepted bets and an auditable ledger. Deleting an account with in-flight bets or overwriting historical attribution would break settlement/reconciliation. No real-money features are in V1.

## Alternatives considered

- Immediate hard deletion and removal of historical records: rejected for ordinary account removal because accepted bets and ledger references must remain auditable.
- Wait until the current round ends to disable: not chosen; access and new betting must stop promptly.
- Disable with preserved ledger/history, then audited owner reassignment: chosen.
- Automatically zero/forfeit a disabled player's wallet: not chosen.

## Decision

1. **Player removal means disablement, not immediate hard deletion.** An authorized owner or the player's assigned agent may disable the player. Invalidate active sessions and block new bets/point-moving actions as soon as the server commits disablement. Existing server-accepted bets remain immutable and settle normally (or receive the approved global void/refund). A pending/unaccepted client draft does not become a bet. A disabled account must not initiate new gameplay. Do not treat a player disconnect or disablement as a reason to alter the global result.
2. **Player wallet after disablement:** preserve and freeze its remaining virtual-point balance after any accepted bets settle; do not automatically zero, forfeit or transfer it. Any future owner-authorized adjustment requires a separate explicit rule, reason and audit entry. The settlement/refund service must still be able to credit the disabled player's wallet exactly once; “frozen” means no new player-initiated actions, not suppression of existing obligations.
3. **Agent removal means disablement.** Invalidate the agent's sessions and stop new agent actions. The owner may reassign that agent's players immediately, even while a round is active. Their accepted bets still settle to their existing player wallets. Reassignment is an audited change of *current* management scope only; never rewrite historical bet, allocation or actor attribution. Authorization must switch atomically to the new agent, without a period when both agents can manage the player.
4. **Unused agent allocation:** reconcile any unused, uncommitted point-allocation budget back to the owner through explicit auditable ledger/budget operations, not by editing or erasing historical entries. The exact budget/reservation representation and concurrent handoff transaction are design work for P02/P05; no points may be created or lost by reassignment.
5. **Privacy deletion is separate from operational removal.** See D-02 for verified requests to anonymize identifying data, subject to the approved retention policy and legal review.

## Security/privacy implications

- Server-side checks must enforce ownership and disabled state on APIs, WebSockets, login and point-moving operations; old sessions must lose access promptly. Audit actor, target, reason, timestamp and any reassignment/budget movement.
- Historical records retain their original references; bet privacy still applies. Admin/agent visibility into historical personal information is subject to D-02 and access controls.
- No hard delete should cascade through ledger, bets or results. Avoid exposing disabled players' private data to an agent who no longer manages them.

## Consequences and follow-up

- P02 schema design: model enabled/disabled state, current agent assignment, immutable historical actor/agent references and transactional handoff; do not implement until separately authorized.
- P03/P04: test session invalidation and cross-agent authorization at disable/reassignment boundaries.
- P05/P06/P07: test wallet freeze vs settlement credits, allocation reconciliation and audit under retries/concurrency.
- D-02 remains partly open: exact retention durations, anonymization eligibility and backup lifecycle need a privacy/legal/operations decision before destructive cleanup or final data lifecycle policy.
