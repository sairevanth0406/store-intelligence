"""
FastAPI Application — Store Intelligence System
Purplle Tech Challenge 2026, Round 2
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os

from app.database import init_db
from app.logging_config import setup_logging, TraceIDMiddleware
from app.ingestion import router as ingestion_router
from app.metrics import router as metrics_router
from app.funnel import router as funnel_router
from app.heatmap import router as heatmap_router
from app.anomalies import router as anomalies_router
from app.brands import router as brands_router
from app.journeys import router as journeys_router
from app.health import router as health_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    setup_logging()
    await init_db()
    yield


app = FastAPI(
    title="Purplle Store Intelligence API",
    description=(
        "Real-time retail analytics from CCTV footage. "
        "Tracks visitors, brand zone engagement, conversion funnels, "
        "anomaly detection, and salesperson attribution."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS for dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TraceIDMiddleware)

# Register routers
app.include_router(ingestion_router, prefix="/events", tags=["Ingestion"])
app.include_router(metrics_router, prefix="/stores", tags=["Metrics"])
app.include_router(funnel_router, prefix="/stores", tags=["Funnel"])
app.include_router(heatmap_router, prefix="/stores", tags=["Heatmap"])
app.include_router(anomalies_router, prefix="/stores", tags=["Anomalies"])
app.include_router(brands_router, prefix="/stores", tags=["Brand Intelligence"])
app.include_router(journeys_router, prefix="/stores", tags=["Journeys"])
app.include_router(health_router, tags=["Health"])

# Serve live dashboard
dashboard_dir = os.path.join(os.path.dirname(__file__), "..", "dashboard")
if os.path.isdir(dashboard_dir):
    app.mount("/dashboard", StaticFiles(directory=dashboard_dir, html=True), name="dashboard")
