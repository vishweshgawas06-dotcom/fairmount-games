# P03-T01c design — Role-binding and provisioning follow-up

**Status:** Documentation draft completed; subsequently superseded by the owner’s broad step-by-step implementation permission. See [P03-T01c implementation](P03-T01c.md).

**Authorization:** Owner first selected “Design next slice only” after P03-T01b completion, then explicitly granted permission to complete phases step by step with testing/debugging. The design-stage restriction applied before that later grant.

## Deliverable

[Role-binding and provisioning design proposal](../auth/NEXT_PROVISIONING_SLICE_DESIGN.md) analyzes P03-T01b's cross-table role gap, proposes a bounded PostgreSQL composite-FK slice with migration safety and test matrix, then separates later provisioning/security work into reviewable gates.

## Design verification

- [x] Compared against approved P03-T01a, P03-T01b, D-10 and current SQLAlchemy/Alembic schema; P03-T01b did not implement role binding or immutability.
- [x] Kept pending owner choices distinct from approved product rules. Migration-fails-on-mismatch and composite FK are **proposals**, not implemented behavior.
- [x] Described PostgreSQL migration, null/role/update/rollback tests and future registration/activation authorization tests without claiming code exists.
- [x] Owner superseded the design-only restriction with broad step-by-step implementation permission; technical composite-FK approach was selected for the bounded DB slice. Unresolved product/security decisions still require owner input.

No new tests are required for a documentation-only task. Existing code/CI evidence for P03-T01b is unchanged. The later permission allows staged work but does not decide unresolved product/security policies by assumption.
