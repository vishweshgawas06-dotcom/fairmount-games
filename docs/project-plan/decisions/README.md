# Architecture and Product Decisions

Record significant decisions as individual dated files. Each decision should include:

- Status: proposed, accepted, superseded, or rejected
- Context and constraints
- Options considered
- Decision and rationale
- Security/privacy implications
- Consequences and follow-up tasks

Do not treat a proposed decision as approved.

## Recorded V1 decisions

- [D-01 — Account disablement, reassignment and point accounting](2026-10-15-account-disable-and-reassignment.md): owner accepted; implementation pending.
- [D-02 — Personal-data deletion and historical retention](2026-10-15-privacy-deletion-and-retention.md): anonymization direction accepted; exact periods and legal/operational review remain open.
- [D-10 — Account provisioning, wallet transfers and game reserve](2026-10-15-account-provisioning-and-point-flow.md): account/transfer flow accepted; reserve capacity rule remains open.
- [D-11 — Username, agent ID and mobile identifiers](2026-10-16-identifier-policy.md): uniqueness and shared-mobile choices accepted; reuse after anonymization deferred.
- [D-03 — Owner MFA and sessions](2026-10-16-owner-mfa-and-sessions.md): TOTP/recovery-code baseline, timeout, step-up and revocation accepted; all-factors-lost manual recovery remains open.
