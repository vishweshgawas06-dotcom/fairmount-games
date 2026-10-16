# D-03 — Owner MFA and browser-session policy

**Status:** Owner-approved baseline on 2026-10-16 for MFA, timeouts, step-up and revocation; all-factors-lost recovery procedure remains unapproved. No authentication/MFA/session code exists yet.

## Context and alternatives

There is one owner account with authority over all agent/player resources and point issuance/transfers. Owner MFA is required before production. Alternatives considered: passkey-first, login-only MFA, weaker email/SMS fallback, and preserving the current session after a reset. Owner selected authenticator-based MFA, one-time recovery codes, recent step-up checks and full affected-session revocation. The one-active-player-session requirement remains in force.

## Approved baseline

1. **Owner MFA:** use a TOTP authenticator factor with one-time offline recovery codes. Store factor secrets encrypted under controlled key management, and store recovery codes as secure one-way hashes; never log or display existing secrets/codes again. Enrollment and recovery require explicit audit and rate limits. Codes are single-use; rotate remaining/replacement codes through a reviewed flow after recovery. MFA must be enforced for owner access before production, not just hidden behind UI controls.
2. **Session timeouts (initial policy):** owner 15 minutes idle / 8 hours absolute; agent 30 minutes idle / 12 hours absolute; player 30 minutes idle / 24 hours absolute. Expiry is enforced on the server for HTTP and realtime; reconnect requires a valid session. **One active session per account for owner, agents and players:** a new login on another device/browser invalidates the older session. Test concurrent logins and stale WebSocket connections for every role.
3. **Owner sensitive actions:** require successful MFA within the previous 10 minutes for issuing/removing points, password/MFA resets, agent provisioning, personal-data deletion actions and other privileged changes. Always enforce owner authorization, reason/audit, idempotency where relevant and server-side checks in addition to step-up. A recent MFA check is not blanket permission to read secrets or manipulate roulette results.
4. **Revocation:** disablement, password reset/change and owner MFA recovery immediately revoke **all affected account sessions**, including the initiating session; fresh login is required. Accepted roulette bets remain valid and settle/void under the approved global policy. WebSocket subscriptions and old cookies must lose access promptly.
5. **Lost authenticator and all recovery codes:** no self-service email/SMS bypass. Stop privileged access. A possible manual ownership-verification process must be designed, threat-reviewed and explicitly approved separately; do not introduce a hidden superuser or code bypass. This can mean prolonged lockout if the owner loses all recovery methods.

## Implementation and test implications (not yet authorized)

- P03 must specify Argon2id password storage, TOTP secret encryption, hashed backup codes, single-use atomic consumption, protected enrollment, reset and recovery, server-clock skew/rate limiting, secure HttpOnly SameSite cookies, CSRF defenses, logout and session invalidation on concurrent requests. Never store or send reusable plaintext passwords by WhatsApp.
- Test absolute versus idle expiry, two concurrent logins for each role, step-up age at 9/11 minutes, recovery-code replay/race, revoked HTTP/WebSocket sessions, disabled accounts, and settlement of already-accepted bets after revocation.
- D-02 retention governs sensitive auth/audit records; operational monitoring, backup/restore of owner MFA secrets and the *manual all-factors-lost process* need separate design approval. No production security certification is claimed by this decision.
