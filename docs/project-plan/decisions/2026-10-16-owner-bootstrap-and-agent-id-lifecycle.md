# D-12 — First-owner bootstrap and fixed Agent IDs

**Status:** Owner-approved direction, 2026-10-16. Implementation is staged; this decision is not evidence that owner login, MFA or credential delivery exists.

## First owner

- V1 has exactly one owner account. The first owner is provisioned by a **trusted, deployment-only local setup command**, not by public registration, an agent, or a browser-accessible bootstrap endpoint.
- The command produces a **single-use initial secret visible once** to the trusted operator; the owner must choose a password and enroll MFA before gaining management access. Do not store or log readable secrets, or permit ordinary management actions from a provisional credential.
- The one-time **initial owner secret expires 24 hours after issuance** if unused. Before activation only, a trusted deployment-only local reissue command may atomically invalidate an unused/expired secret and produce a new once-visible secret, with audit; it may **never** reset the MFA of an activated owner. This pre-activation reissue is not an all-factors-lost recovery path.
- Protect setup execution against accidental repeat or second-owner creation, including concurrent attempts; the existing single-owner PostgreSQL index remains the final guard. The command and initial-secret verifier/audit must be designed and tested alongside activation/MFA. Provide secure, documented out-of-band handoff to the actual owner; do not assume the CLI's operator is the owner. Deployment access control and post-activation recovery still need a separate security review. No self-service all-factors-lost bypass is approved (D-03).
- This decision chooses the **bootstrap route**, not a complete cryptographic/session/operational protocol. Owner setup code must not be implemented by copying agent/player activation behavior without threat review.

## Agent IDs

- Once assigned, an Agent ID is **fixed in V1**, as player usernames are. Do not offer an owner-edit operation, silently rename IDs, or release/reuse one after disabling an agent. Internal account UUIDs and historical attribution must remain stable.
- A database guard for assigned Agent IDs may be added in a separately tested slice. Initial null → generated Agent-ID assignment remains possible for existing/pre-activation rows. D-02/D-11 reuse after approved anonymization, retention and backup policy remain open; this decision does not implement hard deletion.

## Boundaries

This decision does not authorize insecure owner credential distribution, password-reset bypass, login before MFA, agent-created sub-agents, wallets or gameplay changes. [P03-T01a contract](../auth/REGISTRATION_IDENTIFIER_CONTRACT.md) and [D-03](2026-10-16-owner-mfa-and-sessions.md) continue to govern later implementation.
