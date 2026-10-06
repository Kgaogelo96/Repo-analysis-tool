"""FastAPI application entry point for the Repo Analysis Tool."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import routes_metrics, routes_repo

app = FastAPI(
    title="Repo Analysis Tool",
    description="Git repository evolution, volatility and developer-impact dashboard.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_repo.router)
app.include_router(routes_metrics.router)


@app.get("/api/health")
def health() -> dict:
    """Liveness probe used by the frontend to detect a running backend."""
    return {"status": "ok"}
