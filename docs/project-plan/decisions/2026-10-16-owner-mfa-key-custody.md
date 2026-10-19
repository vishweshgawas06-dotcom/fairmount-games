# D-15 — Owner TOTP encryption-key custody

**Status:** Owner-approved V1 local-deployment direction, 2026-10-16. No real key has been generated, requested in chat, committed or stored in PostgreSQL.

- Owner TOTP seeds must be encrypted at rest under an **owner-controlled deployment secret outside the database and repository**. The owner selects a restricted local secret file or environment injection on the deployment host, with a protected offline backup. Do not keep this key in source code, Git, ordinary application logs, browser storage or the same database as encrypted seeds. No hard-coded/default fallback key.
- Record a non-secret key version with each ciphertext to support deliberate rotation. Encryption must authenticate the owner account identity as associated data to prevent swapping ciphertext between accounts. Re-encryption and backup restoration need an audited, tested migration/runbook before production rotation; versioning alone does not constitute a rotation process.
- If the key/backup is lost, the encrypted factor cannot be decrypted. Do not bypass MFA or improvise all-factors-lost recovery; D-03 manual recovery remains unapproved. Key-file permissions, deployment access, backup storage, availability, rotation and incident response need operational review before live owner enrollment.
- The first bounded implementation slice may provide a cryptographic encrypt/decrypt primitive taking a caller-supplied key; loading the key, persistent seed storage, enrollment, recovery-code atomic consumption and owner login remain separate tested work.
