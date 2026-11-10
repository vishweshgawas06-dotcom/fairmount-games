# Owner / admin web app

The incremental owner console is implemented in [the shared operator web app](../operator-web/README.md)
and served at `/console/`. Owner password + MFA, scoped roster and administrative
history, creation/assignment/status controls, one-time pending-secret reissue,
point issuance/transfers and funded-reserve actions use the guarded backend.

The console is unavailable for privileged actions in the ordinary proxy preview.
This is not the complete proposed Next.js app or full P06/release acceptance:
private realtime, complete reporting, active credential/privacy workflows and
staging/security/operations gates remain open. No gameplay P/L or security-event
export is presented as an administrative point journal.
