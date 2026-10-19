# AI Coding Workflow

## Roles

- Cursor: primary implementation assistant.
- Codex: independent reviewer for requirements, security, edge cases, and tests.
- Developer/product owner: final decision-maker; review all changes.

## Required loop

1. Work on one scoped task and its acceptance criteria at a time. Broad owner permission to proceed does not waive scope, security gates or unresolved-decision review.
2. Ask it to inspect existing files before editing.
3. Require a short change plan before multi-file work.
4. Review the diff for unintended edits and requirements drift.
5. Run formatters, type checks, unit tests, integration tests, and relevant E2E tests.
6. Ask the independent reviewer to inspect the diff and test evidence.
7. Resolve findings; do not dismiss security findings without a documented rationale.
8. Update task/status records and commit.

## Prompt discipline

Prompts must name the task ID, allowed scope, prohibited changes, acceptance criteria, and required test commands. Do not ask an AI to "finish the whole project" in one pass. Generated code is untrusted until reviewed and tested.

## Reporting

Report exactly what changed, what commands ran, what passed/failed, and what remains unverified. Never claim zero bugs or guaranteed security.
