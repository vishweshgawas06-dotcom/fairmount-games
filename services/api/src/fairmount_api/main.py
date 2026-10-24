"""FastAPI application entry point for FairMount Games."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from fairmount_api.readiness import database_ready
from fairmount_api.roulette.public_api import router as public_round_router

app = FastAPI(
    title="FairMount Games API",
    version="0.1.0",
    description="Read-only round snapshot; login and gameplay writes are not implemented.",
)
app.include_router(public_round_router)

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
