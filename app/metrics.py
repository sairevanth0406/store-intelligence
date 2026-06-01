"""
GET /stores/{store_id}/metrics — real-time store KPIs.
Purplle Store Intelligence System.
"""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Query
from app.database import get_db
from app.models import StoreMetrics
import structlog

router = APIRouter()
log = structlog.get_logger()


@router.get("/{store_id}/metrics", response_model=StoreMetrics)
async def get_metrics(
    store_id: str,
    window_hours: int = Query(default=24, ge=1, le=168),
):
    """
    Compute real-time store metrics for a rolling time window.
    All values computed from actual events — no hardcoding.
    """
    # PROMPT: Compute unique_visitors (excluding staff), avg dwell, conversion rate
    # via POS correlation, current queue depth, and abandonment rate.
    # CHANGES MADE: Used window-based POS correlation (visitor in CASH_COUNTER zone
    # within 5 min before any transaction = converted). Staff excluded via is_staff flag.

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
        row = await db.execute_fetchall(
            """
            SELECT COUNT(DISTINCT person_id) as cnt
            FROM events
            WHERE store_id=? AND timestamp>=? AND event_type='ENTRY' AND is_staff=0
            """,
            (store_id, window_start),
        )
        unique_visitors = row[0]["cnt"] if row else 0

        # Average dwell time (from sessions)
        row = await db.execute_fetchall(
            """
            SELECT AVG(total_dwell_s) as avg_dwell
            FROM sessions
            WHERE store_id=? AND entry_time>=? AND is_staff=0
            """,
            (store_id, window_start),
        )
        avg_dwell = round(row[0]["avg_dwell"] or 0, 1) if row else 0.0

        # Conversion: unique visitors who had a POS transaction within 5 minutes of visiting CASH_COUNTER
        row_pos_count = await db.execute_fetchall("SELECT COUNT(*) as cnt FROM pos_transactions WHERE store_id=?", (store_id,))
        has_pos = row_pos_count[0]["cnt"] > 0 if row_pos_count else False
        
        if has_pos:
            row = await db.execute_fetchall(
                """
                SELECT COUNT(DISTINCT e.person_id) as cnt
                FROM events e
                JOIN pos_transactions p ON p.store_id = e.store_id
                WHERE e.store_id=? AND e.timestamp>=? AND e.zone_id='CASH_COUNTER' AND e.is_staff=0
                  AND CAST(strftime('%s', p.order_time) AS INTEGER) >= CAST(strftime('%s', e.timestamp) AS INTEGER)
                  AND CAST(strftime('%s', p.order_time) AS INTEGER) <= CAST(strftime('%s', e.timestamp) AS INTEGER) + 300
                """,
                (store_id, window_start),
            )
            converted = row[0]["cnt"] if row else 0
        else:
            # Fallback if no POS transactions are loaded
            row = await db.execute_fetchall(
                """
                SELECT COUNT(DISTINCT person_id) as cnt
                FROM events
                WHERE store_id=? AND timestamp>=? AND zone_id='CASH_COUNTER' AND is_staff=0
                """,
                (store_id, window_start),
            )
            converted = row[0]["cnt"] if row else 0
            
        conversion_rate = round(converted / unique_visitors, 4) if unique_visitors > 0 else 0.0

        # Queue depth: people currently in CASH_COUNTER (ZONE_ENTER - ZONE_EXIT in last 30 min)
        q_start = (now - timedelta(minutes=30)).isoformat()
        row_enter = await db.execute_fetchall(
            "SELECT COUNT(DISTINCT person_id) as cnt FROM events WHERE store_id=? AND timestamp>=? AND zone_id='CASH_COUNTER' AND event_type='ZONE_ENTER' AND is_staff=0",
            (store_id, q_start),
        )
        row_exit = await db.execute_fetchall(
            "SELECT COUNT(DISTINCT person_id) as cnt FROM events WHERE store_id=? AND timestamp>=? AND zone_id='CASH_COUNTER' AND event_type='ZONE_EXIT' AND is_staff=0",
            (store_id, q_start),
        )
        queue_depth = max(0, (row_enter[0]["cnt"] if row_enter else 0) - (row_exit[0]["cnt"] if row_exit else 0))

        # Abandonment: entered but never reached billing zone
        row = await db.execute_fetchall(
            """
            SELECT COUNT(*) as cnt FROM sessions
            WHERE store_id=? AND entry_time>=? AND is_staff=0
            AND converted=0 AND exit_time IS NOT NULL
            """,
            (store_id, window_start),
        )
        abandoned = row[0]["cnt"] if row else 0
        row_total = await db.execute_fetchall(
            "SELECT COUNT(*) as cnt FROM sessions WHERE store_id=? AND entry_time>=? AND is_staff=0",
            (store_id, window_start),
        )
        total_sessions = row_total[0]["cnt"] if row_total else 0
        abandonment_rate = round(abandoned / total_sessions, 4) if total_sessions > 0 else 0.0

        # Top zones by visitor count
        top_rows = await db.execute_fetchall(
            """
            SELECT zone_id, COUNT(DISTINCT person_id) as visitors, AVG(dwell_seconds) as avg_dwell
            FROM events
            WHERE store_id=? AND timestamp>=? AND zone_id IS NOT NULL AND is_staff=0
            GROUP BY zone_id ORDER BY visitors DESC LIMIT 5
            """,
            (store_id, window_start),
        )
        top_zones = [
            {"zone_id": r["zone_id"], "visitors": r["visitors"], "avg_dwell": round(r["avg_dwell"] or 0, 1)}
            for r in top_rows
        ]
    finally:
        await db.close()

    return StoreMetrics(
        store_id=store_id,
        window_start=window_start,
        window_end=now.isoformat(),
        unique_visitors=unique_visitors,
        avg_dwell_seconds=avg_dwell,
        conversion_rate=conversion_rate,
        queue_depth=queue_depth,
        abandonment_rate=abandonment_rate,
        top_zones=top_zones,
        computed_at=now.isoformat(),
    )
