# D-13 — Permanent-password baseline

**Status:** Owner-approved V1 direction, 2026-10-16. Security implementation and threat review are staged; no activation or login endpoint exists yet.

- Owner, agents and players choose a permanent password of **12–128 Unicode characters**. Allow spaces and passphrases; do not require a forced mix of uppercase, digits or symbols. Preserve the exact typed password when hashing/verifying (no implicit trimming, case folding or Unicode normalization).
- Reject a small local list of obvious/common passwords, and prevent whitespace-only or control-character passwords. A later service must rate-limit attempts and protect activation/reset/login endpoints; do not imply a local list alone prevents compromised-password use. Define a bounded input size to prevent excessive hashing work.
- Store only Argon2id hashes with fresh salts, not plaintext or reversible encryption. The [P03-T01f](../tasks/P03-T01f.md) cryptographic helpers now invoke the separately tested policy validator when hashing a new permanent password. Later setup/reset services must use that path and still validate authorization, state and rate limits. Minimum/maximum length applies to passwords the user chooses, **not** the 256-bit generated initial secret.
- Owner MFA remains mandatory before management access. Password policy is not a replacement for D-03 session revocation, TOTP/recovery codes or security audits.
