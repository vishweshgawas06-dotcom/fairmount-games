# Agent web app

The incremental agent console is implemented in [the shared operator web app](../operator-web/README.md)
and served at `/console/`. Agent-ID/password sessions can create self-assigned
players, view only currently enabled assigned players and their scoped
administrative transfers, and transfer points to/from those players without
holders' passwords. No sub-agent creation or owner treasury controls exist in
the agent UI; the backend independently rechecks role and assignment.

Privileged operations remain unavailable in the ordinary proxy preview. This
checkpoint is not the complete proposed Next.js app or full P07/release gate:
private realtime, complete reporting and staging/operations acceptance remain.
