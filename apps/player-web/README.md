# Player Web — read-only preview

The repository contains a **read-only interface prototype** in `preview/`, served by the repository API at `/preview/` (and `/` redirects there). It displays the public server snapshot at `/api/v1/roulette/round` when a migrated PostgreSQL database is explicitly configured with `FAIRMOUNT_API_DATABASE_URL`. Without it the page truthfully shows “Round feed unavailable.” There are **no login, wagering, balances, point transfers or client-selected outcomes**. The number board is display-only. The ball appears only after a persisted server result is revealed. This is not the planned production Next.js/TypeScript client and not a working roulette product.

Run `node --test apps/player-web/tests/*.test.mjs` to verify 37-pocket order, color rules, pre-reveal result gating and ball alignment. Python/FastAPI tests check the preview assets and public snapshot boundary. No external image, font or audio dependencies are required.

Next: approved authenticated contracts and request-edge security, player-specific bet/balance flows, D-08 event/reconnect decision, D-09 owner visual review and device/accessibility/performance testing. See `docs/project-plan/LOCKED_REQUIREMENTS.md` and `docs/project-plan/NEXT_ACTION.md`.
