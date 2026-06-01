"""
Pydantic v2 models for all API schemas.
Purplle Store Intelligence System.
"""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator


# ──────────────────────────────────────────
# Enums
# ──────────────────────────────────────────

class EventType(str, Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    REENTRY = "REENTRY"
    ZONE_ENTER = "ZONE_ENTER"
    ZONE_EXIT = "ZONE_EXIT"
    DWELL = "DWELL"
    ZONE_DWELL = "ZONE_DWELL"
    QUEUE_JOIN = "QUEUE_JOIN"
    QUEUE_EXIT = "QUEUE_EXIT"
    CHECKOUT = "CHECKOUT"
    STAFF_ACTION = "STAFF_ACTION"


class AnomalyType(str, Enum):
    BILLING_QUEUE_SPIKE = "BILLING_QUEUE_SPIKE"
    CONVERSION_DROP = "CONVERSION_DROP"
    DEAD_ZONE = "DEAD_ZONE"
    STALE_FEED = "STALE_FEED"
    BRAND_DWELL_SPIKE = "BRAND_DWELL_SPIKE"


class Severity(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    CRITICAL = "CRITICAL"


# ──────────────────────────────────────────
# Event Schema (ingest)
# ──────────────────────────────────────────

class Event(BaseModel):
    event_id: str = Field(..., description="Unique event UUID — used for idempotent inserts")
    store_id: str = Field(..., description="Store identifier e.g. STORE_BLR_002")
    camera_id: str = Field(..., description="Source camera e.g. CAM1")
    event_type: EventType
    person_id: str = Field(..., description="Stable person track ID within a session")
    is_staff: bool = Field(default=False)
    zone_id: Optional[str] = Field(default=None, description="Zone where event occurred")
    timestamp: datetime = Field(..., description="ISO8601 timestamp of the event")
    dwell_seconds: Optional[float] = Field(default=None, ge=0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: Optional[dict[str, Any]] = Field(default=None)

    @field_validator("timestamp", mode="before")
    @classmethod
    def parse_timestamp(cls, v):
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


class IngestRequest(BaseModel):
    events: list[Event] = Field(..., max_length=500)


class EventResult(BaseModel):
    event_id: str
    status: str  # "ok" | "duplicate" | "error"
    error: Optional[str] = None


class IngestResponse(BaseModel):
    accepted: int
    duplicates: int
    errors: int
    results: list[EventResult]


# ──────────────────────────────────────────
# Metrics
# ──────────────────────────────────────────

class StoreMetrics(BaseModel):
    store_id: str
    window_start: Optional[str]
    window_end: Optional[str]
    unique_visitors: int
    avg_dwell_seconds: float
    conversion_rate: float = Field(..., description="Fraction of visitors with a POS transaction")
    queue_depth: int = Field(..., description="Current people in CASH_COUNTER zone")
    abandonment_rate: float = Field(..., description="Fraction who entered but left without billing zone visit")
    top_zones: list[dict[str, Any]] = Field(default_factory=list)
    computed_at: str


# ──────────────────────────────────────────
# Funnel
# ──────────────────────────────────────────

class FunnelStage(BaseModel):
    stage: str
    count: int
    pct_of_entry: float


class FunnelResponse(BaseModel):
    store_id: str
    window_hours: int
    stages: list[FunnelStage]
    computed_at: str


# ──────────────────────────────────────────
# Heatmap
# ──────────────────────────────────────────

class ZoneHeat(BaseModel):
    zone_id: str
    display_name: str
    category: str
    brand: Optional[str]
    visitor_count: int
    avg_dwell_seconds: float
    heat_score: float = Field(..., description="Normalised 0-100 score")
    data_confidence: str = Field(..., description="high | medium | low based on event count")


class HeatmapResponse(BaseModel):
    store_id: str
    window_hours: int
    zones: list[ZoneHeat]
    max_visitors: int
    computed_at: str


# ──────────────────────────────────────────
# Anomalies
# ──────────────────────────────────────────

class Anomaly(BaseModel):
    anomaly_id: str
    anomaly_type: AnomalyType
    severity: Severity
    zone_id: Optional[str]
    brand: Optional[str]
    description: str
    metric_value: Optional[float]
    threshold: Optional[float]
    suggested_action: str
    detected_at: str


class AnomalyResponse(BaseModel):
    store_id: str
    anomalies: list[Anomaly]
    computed_at: str


# ──────────────────────────────────────────
# Brand Intelligence (UNIQUE)
# ──────────────────────────────────────────

class BrandStat(BaseModel):
    zone_id: str
    brand: Optional[str]
    display_name: str
    category: str
    unique_visitors: int
    avg_dwell_seconds: float
    converted_visitors: int
    conversion_rate: float
    revenue_attributed: float
    top_product: Optional[str]
    heat_rank: int


class BrandIntelligenceResponse(BaseModel):
    store_id: str
    window_hours: int
    brands: list[BrandStat]
    total_revenue: float
    computed_at: str


# ──────────────────────────────────────────
# Shopper Journeys (UNIQUE)
# ──────────────────────────────────────────

class JourneyStop(BaseModel):
    zone_id: str
    display_name: str
    category: str
    dwell_seconds: float
    sequence: int


class ShopperJourney(BaseModel):
    session_id: str
    person_id: str
    entry_time: str
    exit_time: Optional[str]
    total_duration_seconds: float
    converted: bool
    zone_path: list[JourneyStop]
    cameras_seen: list[str]


class JourneysResponse(BaseModel):
    store_id: str
    window_hours: int
    total_journeys: int
    converting_journeys: int
    common_paths: list[dict[str, Any]]
    sample_journeys: list[ShopperJourney]
    computed_at: str


# ──────────────────────────────────────────
# Health
# ──────────────────────────────────────────

class CameraStatus(BaseModel):
    camera_id: str
    last_event_at: Optional[str]
    minutes_since_last_event: Optional[float]
    status: str  # "ok" | "stale" | "no_data"


class HealthResponse(BaseModel):
    status: str  # "healthy" | "degraded" | "unhealthy"
    store_id: str
    cameras: list[CameraStatus]
    db_ok: bool
    last_event_at: Optional[str]
    warnings: list[str]
    checked_at: str
