# Shared owner / agent console

Implemented incremental browser shell at **`/console/`**, served by the FastAPI
application. This is shared, framework-free ES modules/CSS, not a claim that the
original proposed Next.js applications or the complete P06/P07 phases are done.
The public roulette preview remains at `/preview/`.

## Implemented

- Server-derived owner/agent role, exact decimal-string balances and bounded
  current-scope roster / administrative point journal with keyset pagination.
- Owner password + TOTP/recovery sign-in; Agent-ID/password sign-in; logout.
- Member creation, pending setup-secret reissue, status and assignment controls;
  agents can create only their own assigned players, never other agents.
- Owner issuance, owner/member and agent/player transfers; separately funded
  reserve actions. Each write is reviewed, CSRF-protected and idempotent.
- Unknown outcomes retain the exact request key/body and original actor in
  memory. A later denial does not resolve earlier uncertainty. Live context is
  checked before POST using a CSRF snapshot captured **before** that read, so a
  cross-tab session replacement cannot silently change the actor of the intent.
- Secret values are masked, delivered once and erased on dismissal, logout,
  backgrounding or failed authorization. No local/session storage, secret URL
  parameters, HTML interpolation, analytics or third-party assets.
- Responsive desktop/phone/landscape layout, native keyboard-accessible dialogs,
  focus outlines, live status messages, contained table scrolling and CSP.

## Boundary and limitations

The ordinary Arena proxy preview deliberately shows an unavailable/locked state:
**no sample accounts, balances or successful writes are substituted**. Privileged
routes require the existing configured direct-TLS boundary; the console does not
add a forwarding-header trust exception. Use only a configured HTTPS deployment
for real credentials, not the standalone HTTP browser-test server.

Commands are memory-only. Reload/close warns while a request is uncertain, but
cannot provide durable recovery after a browser crash. Review the authorized
journal before a replacement action; never blindly generate a new key. A lost
first-success setup-secret response cannot be recovered by retry: the owner must
reissue a still-pending secret after checking the member state.

Pages recheck authorization on reads, writes, visibility return and a foreground
60-second refresh. This is **not** private realtime revocation or a push feed.
Contact numbers are accepted at creation but excluded from roster/history reads.
No gameplay P/L, security-event export, CSV, activation UI, active-password reset,
all-factors-lost recovery, anonymization workflow or production acceptance is
claimed. Large write amounts are explicitly capped at JavaScript's safe-integer
range; full BIGINT balances display without rounding.

## Checks

```sh
npm ci --ignore-scripts --prefix apps/operator-web
npm test --prefix apps/operator-web
npm run format:check --prefix apps/operator-web
cd apps/operator-web
npx playwright install --with-deps chromium
npm run test:browser
```

Playwright's 11 browser cases use **mocked API contracts**, not live login or
accounting proof. `tests/test_zz_operator_api.py` separately covers real
PostgreSQL HTTP authorization, atomic writes, history scope and cursors.
`tests/test_console_shell.py` exercises real FastAPI headers and fail-closed
preview access. Run all backend tests against a fresh isolated test database.
