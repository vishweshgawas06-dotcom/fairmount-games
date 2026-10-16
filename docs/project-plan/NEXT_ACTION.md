# Next Action

## Completed owner decision checkpoint (2026-10-16)

The owner approved the [D-11 identifier policy](decisions/2026-10-16-identifier-policy.md): player usernames are globally unique and case-insensitive, Agent IDs unique in their own namespace, simple ASCII login identifiers, and mobile numbers may be shared. **Username/Agent-ID reuse after eligible anonymization remains deferred**; D-02 retention/deletion/legal rules are still open.

The owner approved the [D-03 owner MFA/session baseline](decisions/2026-10-16-owner-mfa-and-sessions.md): TOTP plus one-time recovery codes; owner/agent/player idle/absolute timeouts of 15m/8h, 30m/12h and 30m/24h; one active session per account for every role; recent MFA within 10 minutes for sensitive owner actions; all affected sessions revoked on disablement, password reset/change or MFA recovery. No email/SMS self-service bypass when all factors are lost. **A manual all-factors-lost procedure is not designed or approved.** These are rules, not implemented features.

P02-T02a's [existing physical schema](tasks/P02-T02a.md) still has nullable `login_identifier`/mobile fields without unique login indexes; that task is complete for its original scope and is not retroactively a login feature. [CI evidence](https://github.com/vishweshgawas06-dotcom/fairmount-games/actions/runs/38860122010) verifies only the prior schema slice.

## Proposed next small task — separate permission required

**P03-T01a — Identifier normalization and registration contract/design, then a separately reviewed physical constraint slice.** First agree exact allowed lengths, reserved names and Agent-ID format; design case-insensitive uniqueness across all player usernames and separate agent IDs with collision/concurrent-registration tests. Do not implement registration/login or change the existing migration until the task scope and rules are approved. A later P03 task can add secure password activation/reset and owner MFA/session code in independent tested slices.

## Other unresolved decisions

- **D-02 / D-11:** Exact retention, legal holds, deletion/backup rules, username and Agent-ID reuse after anonymization.
- **D-03:** Manual, audited all-factors-lost owner recovery procedure; no hidden bypass.
- **POOL-01:** Owner-funded reserve coverage and any disclosed global bet limit; RNG remains independent.
- **D-06 / OPS-01 / D-04:** Round worker/recovery, atomic settlement at scale and measured operational targets.

No game or authentication feature is production-ready. See [PROJECT_STATUS.md](PROJECT_STATUS.md) and the [delivery plan](DETAILED_DELIVERY_PLAN.md). Obtain separate permission before implementing the next task.
