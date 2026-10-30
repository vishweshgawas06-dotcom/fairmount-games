# Gameplay-write request contract

Status: **contract and tests only; no gameplay write route exists.**

`fairmount_api.identity.write_boundary.require_gameplay_write()` is the single
request-edge envelope a future bet, rebet, transfer or settlement route must
pass before its handler sees user input. It complements, and never replaces,
`resolve_session()` plus the resource checks in the caller's database
transaction.

## What the envelope guarantees

| Check | Reason |
|---|---|
| `POST` only | Gameplay writes are create-only; retried `PUT`/`PATCH` semantics are not approved. |
| One exact `Origin` and `Host` | Cross-site browser writes are rejected before body parsing. Reuses the same-origin session boundary. |
| Exactly one session cookie and one CSRF cookie | Duplicate or ambiguous cookie headers are denied rather than silently collapsed. |
| CSRF header equals CSRF cookie | Double-submit denial for cross-site writes; values are compared in constant time. |
| No query string | Write scope comes from the authenticated session and body, never a URL parameter. |
| `application/json`, optional single `charset=utf-8` | A form, multipart or `text/plain` body is a CORS "simple request" that browsers send cross-site. |
| One `Content-Length` within the byte limit (default 4096) | Bounds memory and rejects oversized payloads before parsing. |
| No `Transfer-Encoding` or `Content-Encoding` | Removes chunked/gzip framing ambiguity between proxy and origin. |
| Streamed bytes equal the declared length | A short or long body is denied instead of being partially interpreted. |
| `Sec-Fetch-Site` absent, `same-origin` or `none` | Hints are used only to deny; absence is not treated as proof of safety. |
| One parseable `Idempotency-Key` (non-zero UUID) | Duplicate submissions can share one persisted key; any accepted spelling normalizes to the same UUID. |
| One JSON object, no duplicate keys, no `NaN`/`Infinity` | Prevents parser-dependent interpretation of the same bytes. |

Denials are indistinguishable (`GameplayWriteUnavailable`, HTTP 400/401 with
`{"status": "unavailable"}`) and never echo the token, cookie, headers or body.

## What the envelope does not guarantee

1. **It is not authority.** A passing envelope only means the request *shape* is
   acceptable. The caller must call `resolve_session()` under locks, repeat live
   role/assignment/resource checks, and reject revoked, expired or disabled
   sessions. The PostgreSQL tests here prove that revocation after a passing
   envelope still denies the write downstream.
2. **Idempotency is not stored yet.** The contract normalizes the key, but no
   unique index or replay table exists. A future write transaction must persist
   it uniquely with the bet and return the original outcome on replay; until
   then a retried request can still duplicate work.
3. **It does not rate limit.** Per-account/per-IP limits, failure accounting and
   abuse budgets are still separate gates (P03-T02i covers private issuance
   throttling only).
4. **It does not validate the body schema.** Each route owns strict field
   validation, amount limits and unknown-field rejection.
5. **It does not address proxy trust.** The direct-TLS origin/Host checks assume
   the ASGI peer is the browser-facing TLS endpoint. A trusted reverse-proxy
   topology, client-IP handling and forwarded-header policy remain undecided, so
   this guard stays disabled behind the HTTP preview proxy.

## Handler order for a future route

1. `require_gameplay_write()` — request envelope and bounded body.
2. Begin the database transaction; `resolve_session()` under `Account` →
   `AccountSession` locks.
3. Re-authorize the actor's live role, enabled state, assignment and target.
4. Validate the body schema; enforce stake/exposure limits under the reserve
   locks used by admission.
5. Persist the idempotency key with the write and commit once.
6. Respond `Cache-Control: no-store`; never include another player's data.
