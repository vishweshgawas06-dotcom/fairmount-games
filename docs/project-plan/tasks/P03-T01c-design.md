# P03-T01c design — Role-binding and provisioning follow-up

**Status:** Documentation draft complete for owner review, 2026-10-16. No P03-T01c migration or application code authorized.

**Authorization:** Owner selected “Design next slice only” after P03-T01b completion. Permission covers this proposal and status documentation, not role-binding implementation, registration, credentials, sessions or wallets.

## Deliverable

[Role-binding and provisioning design proposal](../auth/NEXT_PROVISIONING_SLICE_DESIGN.md) analyzes P03-T01b's cross-table role gap, proposes a bounded PostgreSQL composite-FK slice with migration safety and test matrix, then separates later provisioning/security work into reviewable gates.

## Design verification

- [x] Compared against approved P03-T01a, P03-T01b, D-10 and current SQLAlchemy/Alembic schema; P03-T01b did not implement role binding or immutability.
- [x] Kept pending owner choices distinct from approved product rules. Migration-fails-on-mismatch and composite FK are **proposals**, not implemented behavior.
- [x] Described PostgreSQL migration, null/role/update/rollback tests and future registration/activation authorization tests without claiming code exists.
- [ ] Owner reviews and explicitly approves or revises the proposed DB-only slice before any implementation.

No new tests are required for a documentation-only task. Existing code/CI evidence for P03-T01b is unchanged. Design approval, if given, is not permission for later registration, credentials, sessions or wallets.
