"""
GET /stores/{store_id}/heatmap — brand zone engagement heatmap.
Purplle Store Intelligence System.
"""
import json
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Query
from app.database import get_db
from app.models import HeatmapResponse, ZoneHeat
import structlog

router = APIRouter()
log = structlog.get_logger()

# Zone metadata from store_layout (inline for performance)
ZONE_META = {
    "EB_KOREAN": {"display_name": "EB Korean", "category": "skincare", "brand": "EB Korean (Farm Stay)"},
    "THE_FACE_SHOP": {"display_name": "The Face Shop", "category": "skincare", "brand": "The Face Shop"},
    "GOOD_VIBES": {"display_name": "Good Vibes", "category": "skincare", "brand": "Good Vibes"},
    "DERMDOC": {"display_name": "DermDoc", "category": "skincare", "brand": "DermDoc"},
    "MINIMALIST": {"display_name": "Minimalist", "category": "skincare", "brand": "Minimalist"},
    "AQUALOGICA": {"display_name": "Aqualogica", "category": "skincare", "brand": "Aqualogica"},
    "LAKME_SKIN": {"display_name": "Lakme Skin", "category": "skincare", "brand": "Lakme"},
    "ACCESSORIES": {"display_name": "Accessories", "category": "accessories", "brand": None},
    "MAYBELLINE": {"display_name": "Maybelline", "category": "makeup", "brand": "Maybelline"},
    "FACES_CANADA": {"display_name": "Faces Canada", "category": "makeup", "brand": "Faces Canada"},
    "LAKME": {"display_name": "Lakme Makeup", "category": "makeup", "brand": "Lakme"},
    "COLORBAR_SUGAR": {"display_name": "Colorbar / Sugar", "category": "makeup", "brand": "Colorbar"},
    "SWISS_BEAUTY": {"display_name": "Swiss Beauty", "category": "makeup", "brand": "Swiss Beauty"},
    "RENEE_NYBAE": {"display_name": "Renee / NY Bae", "category": "makeup", "brand": "Renee"},
    "ALPS_GOODNESS": {"display_name": "Alps Goodness", "category": "haircare", "brand": "Alps Goodness"},
    "STREAX": {"display_name": "Streax", "category": "haircare", "brand": "Streax"},
    "FRAGRANCE": {"display_name": "Fragrance", "category": "fragrance", "brand": None},
    "NAIL_UNIT": {"display_name": "Nail Unit", "category": "nails", "brand": None},
    "MAKEUP_UNIT": {"display_name": "Makeup Island", "category": "makeup", "brand": None},
    "CASH_COUNTER": {"display_name": "Cash Counter (Billing)", "category": "billing", "brand": None},
    "PMU": {"display_name": "PMU Service", "category": "service", "brand": None},
    "ENTRY": {"display_name": "Store Entry", "category": "entry", "brand": None},
    "STAFF_AREA": {"display_name": "Staff Area", "category": "staff", "brand": None},
}


@router.get("/{store_id}/heatmap", response_model=HeatmapResponse)
async def get_heatmap(
    store_id: str,
    window_hours: int = Query(default=24, ge=1, le=168),
):
    """
    Returns per-zone visitor count and dwell time, normalised to 0-100 heat score.
    Includes data_confidence flag based on event count reliability.
    """
    db = await get_db()
    try:
        # Anchor to latest event time to support both historical data and live streams
        row_latest = await db.execute_fetchall("SELECT MAX(timestamp) as max_ts FROM events WHERE store_id=?", (store_id,))
        latest_ts_str = row_latest[0]["max_ts"] if row_latest and row_latest[0]["max_ts"] else None
        
        if latest_ts_str:
            now = datetime.fromisoformat(latest_ts_str.replace("Z", "+00:00"))
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
        else:
            now = datetime.now(timezone.utc)

        window_start = (now - timedelta(hours=window_hours)).isoformat()

        rows = await db.execute_fetchall(
            """
            SELECT
                zone_id,
                COUNT(DISTINCT person_id) as visitors,
                AVG(dwell_seconds) as avg_dwell,
                COUNT(*) as event_count
            FROM events
            WHERE store_id=? AND timestamp>=? AND zone_id IS NOT NULL AND is_staff=0
            GROUP BY zone_id
            ORDER BY visitors DESC
            """,
            (store_id, window_start),
        )
    finally:
        await db.close()

    if not rows:
        return HeatmapResponse(
            store_id=store_id, window_hours=window_hours,
            zones=[], max_visitors=0, computed_at=now.isoformat()
        )

    max_visitors = max((r["visitors"] for r in rows), default=1) or 1
    max_dwell = max((r["avg_dwell"] or 0 for r in rows), default=1) or 1

    zones = []
    for r in rows:
        zone_id = r["zone_id"]
        meta = ZONE_META.get(zone_id, {"display_name": zone_id, "category": "unknown", "brand": None})
        visitors = r["visitors"]
        avg_dwell = round(r["avg_dwell"] or 0, 1)
        event_count = r["event_count"]

        # Heat score: 60% weight on visitors, 40% on dwell
        heat_score = round(
            0.6 * (visitors / max_visitors) * 100 +
            0.4 * ((avg_dwell / max_dwell) * 100),
            1,
        )

        # Confidence: based on raw event count
        if event_count >= 20:
            confidence = "high"
        elif event_count >= 5:
            confidence = "medium"
        else:
            confidence = "low"

        zones.append(ZoneHeat(
            zone_id=zone_id,
            display_name=meta["display_name"],
            category=meta["category"],
            brand=meta["brand"],
            visitor_count=visitors,
            avg_dwell_seconds=avg_dwell,
            heat_score=heat_score,
            data_confidence=confidence,
        ))

    return HeatmapResponse(
        store_id=store_id,
        window_hours=window_hours,
        zones=zones,
        max_visitors=max_visitors,
        computed_at=now.isoformat(),
    )
