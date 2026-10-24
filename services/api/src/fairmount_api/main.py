"""FastAPI application entry point for FairMount Games."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from fairmount_api.readiness import database_ready

app = FastAPI(
    title="FairMount Games API",
    version="0.1.0",
    description="Backend API for FairMount Games. Gameplay endpoints are not implemented yet.",
)


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
