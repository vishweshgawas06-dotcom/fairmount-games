"""FastAPI application entry point for FairMount Games."""

from fastapi import FastAPI

app = FastAPI(
    title="FairMount Games API",
    version="0.1.0",
    description="Backend API for FairMount Games. Gameplay endpoints are not implemented yet.",
)


@app.get("/health/live", tags=["health"])
def liveness() -> dict[str, str]:
    """Report that the API process is running; this does not check database readiness."""
    return {"status": "ok", "service": "fairmount-api"}
