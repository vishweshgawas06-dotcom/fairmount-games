# D-02 — Personal-data deletion and historical retention

**Status:** Partially accepted by owner on 2026-10-15. Anonymization approach chosen; retention periods and legal/operational constraints remain unresolved. Not authorization to perform deletion.

## Context

Player accounts store name/mobile and user ID; the game produces bet, wallet, ledger, allocation, result and audit records. Account disablement (D-01) is not a personal-data deletion request. An accounting trail must survive without exposing unnecessary personal information. Applicable privacy, accounting and backup obligations require review for the deployment jurisdiction; no legal compliance claim is made here.

## Alternatives considered

- Immediate full deletion of account, bets and point ledger: not chosen; would compromise audit and reconciliation.
- Disable only, retain identifying details indefinitely: not chosen as the long-term deletion policy.
- On an authenticated/verified eligible request, remove or irreversibly anonymize identifying fields while retaining non-identifying accounting/game references: chosen in principle, subject to legal retention exceptions and an implementation design.
- Set arbitrary retention durations now or retain everything forever: not chosen. Owner deferred exact periods until privacy/legal/operations review.

## Decision (approved direction)

1. Keep operational disablement and a verified personal-data deletion request as separate workflows. Only authorized staff may process a verified request; log who approved/performed it and why, without re-exposing erased identifiers.
2. When eligible under the **later approved** retention/deletion policy, delete or irreversibly anonymize personal identifying fields such as name, mobile and other identifying metadata. Preserve only non-identifying bet/round/ledger/audit records needed to maintain accounting integrity; do not assume a user ID is automatically anonymous if it can be linked back to a person.
3. Do not hard-delete or mutate accepted bet amounts, settled results, point ledger entries or their audit trail to fulfill an ordinary removal request. Restrict access to retained records.
4. Do not run destructive/anonymization jobs until durations, lawful exceptions, backups, idempotent processing, references/exports and restore behavior have been reviewed and approved. Do not promise immediate erasure from immutable backups without an approved retention/expiry strategy.

## Explicitly open before final data lifecycle design

- Periods for active-account personal data, disabled-account personal data, detailed player gameplay history, ledger/audit records, security logs and backups; start event for each timer and any legal holds.
- Identity-verification/approval process, downstream copies, export rights, data minimization, and treatment of shared mobile numbers where they are used for contact/reset delivery.
- [D-11](2026-10-16-identifier-policy.md) approves global case-insensitive player username uniqueness and non-unique mobile numbers, but **defers old username reuse after anonymization**; agent-ID reuse/retention also needs a decision. Neither identity reuse nor deletion jobs are implemented.
- Jurisdiction-specific legal/privacy review and production-facing disclosure; no retention period is invented in this decision.

## Security/privacy implications and follow-up

- P02-T01 may *design* schema separation of identifying data, stable opaque non-personal references, audited disablement and configurable retention categories. Treat any final migration or destructive cleanup that relies on unresolved durations as blocked pending owner/legal approval.
- P03/P04/P06/P07 must restrict who can request, view or execute deletion and ensure disabled/anonymized accounts cannot log in. Tests must check API, realtime, backups/restore and leakage in logs/exports.
- P18 launch gate includes approval of actual retention windows, privacy disclosures and deletion/restore runbooks. Until then D-02 is **not fully closed**.
