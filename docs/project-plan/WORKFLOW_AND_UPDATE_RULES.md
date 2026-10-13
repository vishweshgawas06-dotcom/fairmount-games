# Workflow and Update Rules

## For every task

1. Read the task and relevant locked requirements.
2. Identify dependencies and unresolved decisions.
3. Make the smallest change that satisfies the task.
4. Run relevant automated checks; report commands and outcomes accurately.
5. Review security, authorization, error handling, and regressions.
6. Update the task, PROJECT_STATUS.md, NEXT_ACTION.md, and related docs.
7. Commit with a clear, scoped message.

## Never

- Guess at a missing product rule.
- Claim tests passed without running them.
- claim production readiness based on a local demo.
- Trust the client for balance, outcome, timing, role, or permission.
- Weaken authorization to make a test pass.
- Put secrets or real user data in source control.
- Rewrite unrelated files without justification.
- Add real-money features to V1.

## Decisions

Record material architecture/product decisions in docs/project-plan/decisions/ with context, alternatives, decision, and consequences. If a decision is not approved, mark it proposed or unresolved.

## Task completion

A task is complete only when its acceptance criteria have evidence. If a test cannot be run, say so and keep the task open unless the acceptance criteria explicitly allow a documented exception.
