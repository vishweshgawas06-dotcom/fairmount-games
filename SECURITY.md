# Security Policy — FairMount Games

## Scope

Version 1 is a virtual-points product. Real-money wagering, deposits, withdrawals, cash-equivalent prizes, and payment processing are out of scope. Any future change requires a separate written decision, legal review for each target jurisdiction, and a security review.

## Non-negotiable controls

- Hash passwords using Argon2id with appropriately configured parameters.
- Require multi-factor authentication for owner/admin accounts before production.
- Use HTTPS in deployed environments and secure, HttpOnly, SameSite cookies for browser sessions.
- Apply least privilege and server-side resource-level authorization on every protected operation.
- Rate-limit authentication and sensitive actions; validate inputs on the server.
- Use database transactions, constraints, and idempotency for bets and point-ledger changes.
- Keep roulette result generation independent of player bets.
- Record auditable administrative point changes with actor, target, amount, reason, timestamp, and correlation context.
- Never log passwords, session tokens, or other secrets.
- Keep secrets out of Git; use environment configuration or a managed secret store.
- Apply an OWASP ASVS 5 baseline and document exceptions.

## Reporting

Do not publish exploit details or real user data in public issues. Report suspected vulnerabilities privately to the repository owner and include reproduction steps that avoid exposing secrets.

## Release gate

A release is not production-ready until automated tests, authorization checks, dependency/security review, backup/restore verification, monitoring, and a documented rollback procedure have been completed. Do not claim security certification based solely on this checklist.
