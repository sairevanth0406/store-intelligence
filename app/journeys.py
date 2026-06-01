"""
GET /stores/{store_id}/journeys — Shopper journey reconstruction (UNIQUE endpoint).
Purplle Store Intelligence System.
"""
import json
from datetime import datetime, timezone, timedelta
from collections import Counter
from fastapi import APIRouter, Query
from app.database import get_db
from app.models import JourneysResponse, ShopperJourney, JourneyStop
from app.heatmap import ZONE_META
import structlog

router = APIRouter()
log = structlog.get_logger()


@router.get("/{store_id}/journeys", response_model=JourneysResponse)
async def get_journeys(
    store_id: str,
    window_hours: int = Query(default=24, ge=1, le=168),
    limit: int = Query(default=10, ge=1, le=50),
):
    """
    Reconstruct shopper journeys from session + event data.
    Identifies most common zone-to-zone paths (purchase vs non-purchase).
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
        sessions = await db.execute_fetchall(
            """
            SELECT session_id, person_id, entry_time, exit_time, converted, zones_visited, total_dwell_s
            FROM sessions
            WHERE store_id=? AND entry_time>=? AND is_staff=0
            ORDER BY entry_time DESC LIMIT 100
            """,
            (store_id, window_start),
        )

        # Get camera IDs seen per person
        cam_rows = await db.execute_fetchall(
            """
            SELECT person_id, GROUP_CONCAT(DISTINCT camera_id) as cams
            FROM events
            WHERE store_id=? AND timestamp>=? AND is_staff=0
            GROUP BY person_id
            """,
            (store_id, window_start),
        )
        cam_map = {r["person_id"]: (r["cams"] or "").split(",") for r in cam_rows}

        # Zone dwell per person
        zone_dwell_rows = await db.execute_fetchall(
            """
            SELECT person_id, zone_id, SUM(dwell_seconds) as total_dwell
            FROM events
            WHERE store_id=? AND timestamp>=? AND zone_id IS NOT NULL AND dwell_seconds IS NOT NULL AND is_staff=0
            GROUP BY person_id, zone_id
            """,
            (store_id, window_start),
        )
        # person_id -> {zone_id -> dwell}
        dwell_map: dict[str, dict[str, float]] = {}
        for row in zone_dwell_rows:
            pid = row["person_id"]
            if pid not in dwell_map:
                dwell_map[pid] = {}
            dwell_map[pid][row["zone_id"]] = row["total_dwell"]
    finally:
        await db.close()

    journeys: list[ShopperJourney] = []
    path_counter: Counter = Counter()
    converting_count = 0

    for sess in sessions:
        zones_visited = json.loads(sess["zones_visited"] or "[]")
        if not zones_visited:
            continue

        person_id = sess["person_id"]
        converted = bool(sess["converted"])
        if converted:
            converting_count += 1

        # Build ordered stops with dwell
        stops: list[JourneyStop] = []
        for seq, zone_id in enumerate(zones_visited):
            meta = ZONE_META.get(zone_id, {"display_name": zone_id, "category": "unknown"})
            dwell = dwell_map.get(person_id, {}).get(zone_id, 0.0)
            stops.append(JourneyStop(
                zone_id=zone_id,
                display_name=meta["display_name"],
                category=meta["category"],
                dwell_seconds=round(dwell, 1),
                sequence=seq + 1,
            ))

        # Build path string for common path analysis
        path_key = " → ".join(z for z in zones_visited if z not in ("ENTRY", "STAFF_AREA"))
        if path_key:
            path_counter[path_key] += 1

        entry_time = sess["entry_time"]
        exit_time = sess["exit_time"]
        total_duration = sess["total_dwell_s"] or 0.0

        journeys.append(ShopperJourney(
            session_id=sess["session_id"],
            person_id=person_id,
            entry_time=entry_time,
            exit_time=exit_time,
            total_duration_seconds=round(total_duration, 1),
            converted=converted,
            zone_path=stops,
            cameras_seen=cam_map.get(person_id, []),
        ))

    # Top common paths
    common_paths = [
        {"path": path, "count": count}
        for path, count in path_counter.most_common(5)
    ]

    return JourneysResponse(
        store_id=store_id,
        window_hours=window_hours,
        total_journeys=len(journeys),
        converting_journeys=converting_count,
        common_paths=common_paths,
        sample_journeys=journeys[:limit],
        computed_at=now.isoformat(),
    )
