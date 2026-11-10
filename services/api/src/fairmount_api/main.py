"""FastAPI application entry point for FairMount Games."""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from fairmount_api.console_api import router as console_router
from fairmount_api.identity.activation_api import router as activation_router
from fairmount_api.identity.login_api import router as direct_login_router
from fairmount_api.identity.operator_api import router as operator_router
from fairmount_api.private_read_api import router as private_read_router
from fairmount_api.private_stream_api import router as private_stream_router
from fairmount_api.readiness import database_ready
from fairmount_api.roulette.player_bet_api import router as player_bet_router
from fairmount_api.roulette.public_api import router as public_round_router

app = FastAPI(
    title="FairMount Games API",
    version="0.1.0",
    description=(
        "Read-only round snapshot, opt-in direct-TLS login, bet write and "
        "owner/agent operator writes; gameplay is not publicly enabled."
    ),
)
app.include_router(public_round_router)
app.include_router(direct_login_router)
app.include_router(private_read_router)
app.include_router(private_stream_router)
app.include_router(player_bet_router)
app.include_router(operator_router)
app.include_router(activation_router)
app.include_router(console_router)

# Static operator shell is viewable in the proxy preview, but its APIs retain
# the direct-TLS authorization boundary. No insecure auth override is introduced.
_console_dir = Path(__file__).resolve().parents[4] / "apps/operator-web/web"
if _console_dir.is_dir():
    app.mount("/console", StaticFiles(directory=str(_console_dir), html=True), name="console")


@app.middleware("http")
async def console_security_headers(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/console/"):
        policy = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
            "base-uri 'none'; form-action 'self'"
        )
        # Production operator pages must not be framed. The nonfunctional
        # default preview shell remains embeddable in Arena's viewer.
        if os.environ.get("FAIRMOUNT_AUTH_EDGE_MODE") == "direct-tls":
            policy += "; frame-ancestors 'self'"
        response.headers["Content-Security-Policy"] = policy
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response


# Repository-only read-only interface. An installed API wheel can run without
# the frontend tree; production UI hosting is a separate deployment gate.
_preview_dir = Path(__file__).resolve().parents[4] / "apps/player-web/preview"
if _preview_dir.is_dir():
    app.mount(
        "/preview", StaticFiles(directory=str(_preview_dir), html=True), name="player-preview"
    )

    @app.get("/", include_in_schema=False)
    def preview_home() -> RedirectResponse:
        return RedirectResponse("/preview/", status_code=307)


@app.get("/health/live", tags=["health"])
def liveness() -> dict[str, str]:
    """Report that the API process is running; this does not check database readiness."""
    return {"status": "ok", "service": "fairmount-api"}


@app.get("/health/ready", tags=["health"])
def readiness() -> JSONResponse:
    """Fail closed without a reachable, migrated PostgreSQL API database.

    Not a worker/solvency probe; do not use this to announce game availability.
    """
    if not database_ready():
        return JSONResponse(
            {"status": "unavailable"}, status_code=503, headers={"Cache-Control": "no-store"}
        )
    return JSONResponse({"status": "ready"}, status_code=200, headers={"Cache-Control": "no-store"})
