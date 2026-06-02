"""
GET /stores/{store_id}/funnel — customer journey conversion funnel.
Purplle Store Intelligence System.
"""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Query
from app.database import get_db
from app.models import FunnelResponse, FunnelStage
import structlog

router = APIRouter()
log = structlog.get_logger()


@router.get("/{store_id}/funnel", response_model=FunnelResponse)
async def get_funnel(
    store_id: str,
    window_hours: int = Query(default=24, ge=1, le=168),
):
    """
    Entry → Browse (any zone) → High-Intent Zone → Billing → Purchase funnel.
    Each stage = unique non-staff visitors who reached that stage.
    Re-entries counted once per session.
    """
    # PROMPT: Build a 5-stage funnel. Use session-based deduplication so re-entry
    # visitors are counted once. High-intent zones = CASH_COUNTER proximity zones.
    # CHANGES MADE: Stage 3 is brand zone engagement (not just any zone), making
    # the funnel retail-specific rather than generic.

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

        # Stage 1: Entry
        row = await db.execute_fetchall(
            "SELECT COUNT(DISTINCT person_id) as cnt FROM events WHERE store_id=? AND timestamp>=? AND event_type='ENTRY' AND is_staff=0",
            (store_id, window_start),
        )
        entry_count = row[0]["cnt"] if row else 0

        # Stage 2: Browse (visited at least one product zone)
        row = await db.execute_fetchall(
            """
            SELECT COUNT(DISTINCT person_id) as cnt FROM events
            WHERE store_id=? AND timestamp>=? AND event_type IN ('ZONE_ENTER','DWELL','ZONE_DWELL')
            AND zone_id NOT IN ('ENTRY','STAFF_AREA','CASH_COUNTER') AND is_staff=0
            """,
            (store_id, window_start),
        )
        browse_count = row[0]["cnt"] if row else 0

        # Stage 3: Deep Browse (dwell > 30s in a brand zone)
        row = await db.execute_fetchall(
            """
            SELECT COUNT(DISTINCT person_id) as cnt FROM events
            WHERE store_id=? AND timestamp>=? AND event_type IN ('DWELL','ZONE_DWELL')
            AND dwell_seconds >= 30 AND zone_id NOT IN ('ENTRY','STAFF_AREA','CASH_COUNTER') AND is_staff=0
            """,
            (store_id, window_start),
        )
        deep_browse_count = row[0]["cnt"] if row else 0

        # Stage 4: Billing intent (visited CASH_COUNTER)
        row = await db.execute_fetchall(
            "SELECT COUNT(DISTINCT person_id) as cnt FROM events WHERE store_id=? AND timestamp>=? AND zone_id='CASH_COUNTER' AND is_staff=0",
            (store_id, window_start),
        )
        billing_count = row[0]["cnt"] if row else 0

        # Stage 5: Purchase (correlated via POS or CHECKOUT)
        row = await db.execute_fetchall(
            """
            SELECT COUNT(DISTINCT e.person_id) as cnt
            FROM events e
            WHERE e.store_id=? AND e.timestamp>=? AND e.is_staff=0
              AND (
                  e.event_type = 'CHECKOUT'
                  OR
                  (e.zone_id='CASH_COUNTER' AND EXISTS (
                      SELECT 1 FROM pos_transactions p
                      WHERE p.store_id = e.store_id
                        AND CAST(strftime('%s', p.order_time) AS INTEGER) >= CAST(strftime('%s', e.timestamp) AS INTEGER)
                        AND CAST(strftime('%s', p.order_time) AS INTEGER) <= CAST(strftime('%s', e.timestamp) AS INTEGER) + 300
                  ))
              )
            """,
            (store_id, window_start),
        )
        purchase_count = row[0]["cnt"] if row else 0
    finally:
        await db.close()

    def pct(n):
        return round(n / entry_count, 4) if entry_count > 0 else 0.0

    stages = [
        FunnelStage(stage="Entry", count=entry_count, pct_of_entry=1.0),
        FunnelStage(stage="Browse (Zone Visit)", count=browse_count, pct_of_entry=pct(browse_count)),
        FunnelStage(stage="Deep Browse (30s+ Dwell)", count=deep_browse_count, pct_of_entry=pct(deep_browse_count)),
        FunnelStage(stage="Billing Intent", count=billing_count, pct_of_entry=pct(billing_count)),
        FunnelStage(stage="Purchase (Checkout)", count=purchase_count, pct_of_entry=pct(purchase_count)),
    ]

    return FunnelResponse(
        store_id=store_id,
        window_hours=window_hours,
        stages=stages,
        computed_at=now.isoformat(),
    )
