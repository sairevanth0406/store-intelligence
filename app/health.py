"""
GET /health — liveness check with per-camera staleness detection.
Purplle Store Intelligence System.
"""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter
from app.database import get_db
from app.models import HealthResponse, CameraStatus
import structlog

router = APIRouter()
log = structlog.get_logger()

STALE_MINUTES = 10
KNOWN_CAMERAS = ["CAM1", "CAM2", "CAM3", "CAM4", "CAM5"]


@router.get("/health", response_model=HealthResponse)
async def health_check(store_id: str = "STORE_BLR_002"):
    """Check system health. Warns if any camera feed is stale (>10 min)."""
    now = datetime.now(timezone.utc)
    db_ok = False
    cameras: list[CameraStatus] = []
    warnings: list[str] = []
    last_event_at = None
    overall_status = "healthy"

    try:
        db = await get_db()
        try:
            db_ok = True
            
            # Anchor to latest event time to support both historical data and live streams
            row_latest = await db.execute_fetchall("SELECT MAX(timestamp) as max_ts FROM events WHERE store_id=?", (store_id,))
            latest_ts_str = row_latest[0]["max_ts"] if row_latest and row_latest[0]["max_ts"] else None
            
            if latest_ts_str:
                anchor_now = datetime.fromisoformat(latest_ts_str.replace("Z", "+00:00"))
                if anchor_now.tzinfo is None:
                    anchor_now = anchor_now.replace(tzinfo=timezone.utc)
            else:
                anchor_now = now

            for cam_id in KNOWN_CAMERAS:
                row = await db.execute_fetchall(
                    "SELECT MAX(timestamp) as last_ts FROM events WHERE store_id=? AND camera_id=?",
                    (store_id, cam_id),
                )
                last_ts_str = row[0]["last_ts"] if row and row[0]["last_ts"] else None

                if not last_ts_str:
                    cameras.append(CameraStatus(
                        camera_id=cam_id,
                        last_event_at=None,
                        minutes_since_last_event=None,
                        status="no_data",
                    ))
                    warnings.append(f"{cam_id}: no events received yet")
                    continue

                last_ts = datetime.fromisoformat(last_ts_str.replace("Z", "+00:00"))
                if last_ts.tzinfo is None:
                    last_ts = last_ts.replace(tzinfo=timezone.utc)
                delta_min = (anchor_now - last_ts).total_seconds() / 60

                if delta_min > STALE_MINUTES:
                    status = "stale"
                    warnings.append(f"{cam_id}: STALE_FEED — last event {delta_min:.1f} min ago")
                else:
                    status = "ok"

                cameras.append(CameraStatus(
                    camera_id=cam_id,
                    last_event_at=last_ts.isoformat(),
                    minutes_since_last_event=round(delta_min, 1),
                    status=status,
                ))

                if not last_event_at or last_ts_str > last_event_at:
                    last_event_at = last_ts_str
        finally:
            await db.close()

    except Exception as exc:
        db_ok = False
        warnings.append(f"DB error: {exc}")
        overall_status = "unhealthy"

    if warnings:
        # Ignore warning if it's just camera 'no_data' at startup, unless there are active stalenesses
        has_stale_camera = any(c.status == "stale" for c in cameras)
        if has_stale_camera or not db_ok:
            overall_status = "degraded" if db_ok else "unhealthy"
        else:
            overall_status = "healthy"

    return HealthResponse(
        status=overall_status,
        store_id=store_id,
        cameras=cameras,
        db_ok=db_ok,
        last_event_at=last_event_at,
        warnings=warnings,
        checked_at=now.isoformat(),
    )
