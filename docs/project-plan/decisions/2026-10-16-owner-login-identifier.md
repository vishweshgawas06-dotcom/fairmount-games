# D-14 — Single-owner login identifier

**Status:** Owner-approved product rule, 2026-10-16. No owner login or MFA endpoint exists yet.

- The single V1 owner signs in with the fixed, public word **`owner`** plus a permanent password and required MFA. It is an identifier, **not** a secret or authorization token. The server resolves it to the unique `accounts.role = 'OWNER'` account; no second owner account, owner self-registration, owner email login or generated owner ID is part of V1.
- `owner` is reserved in the player-username contract; player/agent identifiers remain in their own namespaces. Never weaken the existing player/agent case-insensitive uniqueness or role-binding checks to add owner login. A future login service must normalize and compare the owner login label intentionally, guard against enumeration and brute force, and enforce account status, activated credentials, completed owner MFA, session policy, authorization and audit.
- The owner-run deployment-only bootstrap command (D-12) may create the sole OWNER account with a pending credential and minimal security event. That is **not** permission to enter a dashboard until the owner has set a permanent password and enrolled TOTP/recovery codes. No registration or login route is implemented by this decision.
