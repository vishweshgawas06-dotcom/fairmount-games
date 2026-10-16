# D-11 — Player username, agent ID and mobile identifier policy

**Status:** Partially accepted by owner on 2026-10-16. Login identifier uniqueness choices approved; username reuse after eligible anonymization remains open. No registration/login feature is implemented.

## Context

Owner and agents provision accounts; players sign in by username/password and agents by Agent ID/password. The first physical schema intentionally left `private_identities.login_identifier` nullable and without a uniqueness constraint pending this decision. D-02 privacy deletion/retention is only partially approved; permanent tombstones can retain identifying information and re-identify records. Mobile is stored as profile/contact information, not login authority.

## Alternatives and decision

- **Player usernames:** globally unique across *all* players, including different agents and owner-managed players, with case-insensitive matching. Only simple ASCII letters, digits, underscore/hyphen are allowed in login identifiers; exact length/reserved-name rules remain a scoped design choice. Per-agent uniqueness (which would require an Agent ID at player login) was not selected. Ownership/reassignment must not alter a player's login identity.
- **Agent IDs:** unique platform-wide in their own agent namespace, distinct from player usernames. Player usernames and Agent IDs use a simple ASCII identifier set (letters, digits, underscore/hyphen) with case-insensitive matching; display names may use other scripts. Exact length, reserved-name rules and whether Agent IDs are ever reusable remain design/privacy questions; avoid exposing internal UUIDs needlessly.
- **Mobile numbers:** not unique; multiple accounts may share a number. A mobile number alone cannot select an account, authenticate a person or authorize a password reset. If used for contact or reset delivery, an independent account identity and verified procedure are required. Do not expose another account merely because a number matches.
- **Old username after verified eligible anonymization:** owner explicitly **deferred** whether it can be reused. Do not implement a hard-delete, a permanent identifier tombstone, or a released username policy until D-02 retention/legal and unlinking rules are approved. Disabled accounts still retain their identity until a separate eligible deletion process is approved.

## Security and privacy implications

- Before enabling registration/login, define exact ASCII case normalization, minimum/maximum length, reserved names and collision behavior; apply them server-side and with a PostgreSQL unique key/index, then test concurrent creations and name changes. This document approves *case-insensitive global uniqueness*, not a particular SQL implementation or automatic username reuse. Avoid silent normalization that maps two existing usernames to one account.
- Agent dashboards continue to show only enabled currently assigned players; owner sees all authorized accounts. A shared mobile number confers no access to other users' accounts.
- Unique login identifiers are personal data if they can link to a person; D-02 controls export, retention, anonymization and backups. The first schema migration need not be rewritten retroactively; use a future scoped migration after checking actual data for collisions.

## Follow-up

- P03/P04: specify username/Agent-ID creation and reset/activation flows, server-side normalization, explicit credential delivery and resource-level authorization. Test duplicate case variants across agents, concurrent creation, owner-managed players and shared mobile numbers.
- D-02/PRIV-01: owner/legal review of username and Agent-ID reuse/retention and how references are irreversibly severed, before any destructive/anonymization job.
- No wallet/game behavior changes and no implementation permission is implied by this decision.
