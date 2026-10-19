# Workflow and Update Rules

## For every task

1. Read the approved delivery plan, task brief, and relevant locked requirements. The owner granted permission to implement all phases in bounded, tested steps; do not ask for per-task permission. Ask the owner before making a genuinely unresolved product or security decision, and never implement a blocked dependent flow by guessing.
2. Identify dependencies and unresolved decisions; do not guess at them.
3. Make the smallest change that satisfies the task. Keep code readable, reviewable, and consistently formatted; add validation and appropriate error handling, with user-facing failure states where relevant. Aim for correctness, but never claim code is error-free without evidence.
4. Run applicable formatting, lint, type checks, unit, integration, security, and UI/E2E tests; debug failures before advancing. Report the exact commands, environment, results, and anything not verified.
5. Review security, authorization, accounting, error handling, accessibility, and regressions relevant to the change. For UI work, use an original, coherent design with accessible colors, typography, icons/SVGs, responsive layouts, and licensed assets; do not assume visual polish substitutes for usability.
6. After each completed task/stage, update its task record, PROJECT_STATUS.md, NEXT_ACTION.md, and related Markdown documentation with accurate status and evidence. Do not mark a stage complete until its acceptance gate passes or an approved exception is recorded.
7. Commit with a clear, scoped message and push the completed checkpoint to the authorized GitHub branch after reviewing the diff. Record push failures honestly and do not claim GitHub has a change until the push succeeds. Commit/push additional checkpoints when appropriate; never commit secrets or unreviewed generated artifacts.

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
