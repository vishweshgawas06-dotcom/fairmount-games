# Next Action

## Active review — P03-T01c design only

The owner authorized **documentation only** after P03-T01b. Review the [P03-T01c role-binding and provisioning proposal](auth/NEXT_PROVISIONING_SLICE_DESIGN.md) and its [design task](tasks/P03-T01c-design.md). It proposes a separate database-only migration to bind non-null identity login kind to account role, with PostgreSQL migration/constraint tests. **No P03-T01c code or migration is authorized or implemented.** The composite FK and fails-on-legacy-mismatch policy are proposals for owner review, not accepted decisions.

**Next:** owner reviews/corrects the design and, if desired, expressly authorizes a small implementation scope. Registration endpoints, activation credentials, sessions, wallets, fixed-name enforcement and deletion/reuse need their own design/permission and verification gates. The current P03-T01b database constraints alone do not register or authenticate anyone.

## Completed checkpoints

[P03-T01a](tasks/P03-T01a.md) approved contract: fixed globally unique case-insensitive player usernames, generated Agent IDs, reserved names, shared/unverified mobile and single-use 24-hour initial credentials (not implemented). [P03-T01b](tasks/P03-T01b.md) canonical ID helpers/DB constraints passed [CI run 38862897157](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38862897157). [P02-T02a](tasks/P02-T02a.md) account/identity/assignment schema passed [CI run 38859943741](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38859943741) on PostgreSQL 16.9. Docker is unavailable locally; no login or wallet code exists.

## Other open decisions

- **D-02 / D-11:** Retention, deletion/backups, username/Agent-ID reuse after anonymization.
- **D-03:** Manual owner recovery if both TOTP and all offline codes are lost; no self-service bypass.
- **POOL-01:** Funded reserve coverage/global bet acceptance rule; RNG remains independent.
- **D-06 / OPS-01 / D-04:** Round recovery, atomic settlement under load, measurable operational targets.

See [PROJECT_STATUS.md](PROJECT_STATUS.md) and the [delivery plan](DETAILED_DELIVERY_PLAN.md). Planning approval is not production-readiness evidence.
