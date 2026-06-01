"""
GET /stores/{store_id}/anomalies — real-time anomaly detection.
Purplle Store Intelligence System.
"""
import uuid
import os
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Query
from app.database import get_db
from app.models import AnomalyResponse, Anomaly, AnomalyType, Severity
import structlog

router = APIRouter()
log = structlog.get_logger()

# Configurable via environment
QUEUE_WARN = int(os.environ.get("QUEUE_SPIKE_WARN", 3))
QUEUE_CRITICAL = int(os.environ.get("QUEUE_SPIKE_CRITICAL", 6))
CONV_WARN_PCT = float(os.environ.get("CONV_DROP_WARN", 0.80))
CONV_CRITICAL_PCT = float(os.environ.get("CONV_DROP_CRITICAL", 0.60))
DEAD_ZONE_MIN = int(os.environ.get("DEAD_ZONE_MINUTES", 30))


@router.get("/{store_id}/anomalies", response_model=AnomalyResponse)
async def get_anomalies(
    store_id: str,
    window_hours: int = Query(default=1, ge=1, le=24),
):
    """
    Detect: BILLING_QUEUE_SPIKE, CONVERSION_DROP, DEAD_ZONE, BRAND_DWELL_SPIKE.
    All thresholds configurable via environment variables.
    """
    # PROMPT: Build anomaly detection. For CONVERSION_DROP, compare today vs 7-day avg.
    # CHANGES MADE: Added BRAND_DWELL_SPIKE — flags if a brand zone has unusually high
    # dwell (restock opportunity or product interest signal).

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
        anomalies: list[Anomaly] = []
        # 1. BILLING_QUEUE_SPIKE
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

        if queue_depth >= QUEUE_CRITICAL:
            anomalies.append(Anomaly(
                anomaly_id=str(uuid.uuid4()),
                anomaly_type=AnomalyType.BILLING_QUEUE_SPIKE,
                severity=Severity.CRITICAL,
                zone_id="CASH_COUNTER",
                brand=None,
                description=f"Billing queue critically high: {queue_depth} customers waiting",
                metric_value=float(queue_depth),
                threshold=float(QUEUE_CRITICAL),
                suggested_action="Open additional billing counter immediately. Alert store manager.",
                detected_at=now.isoformat(),
            ))
        elif queue_depth >= QUEUE_WARN:
            anomalies.append(Anomaly(
                anomaly_id=str(uuid.uuid4()),
                anomaly_type=AnomalyType.BILLING_QUEUE_SPIKE,
                severity=Severity.WARN,
                zone_id="CASH_COUNTER",
                brand=None,
                description=f"Billing queue building: {queue_depth} customers waiting",
                metric_value=float(queue_depth),
                threshold=float(QUEUE_WARN),
                suggested_action="Redirect beauty advisor to assist at billing counter.",
                detected_at=now.isoformat(),
            ))

        # 2. CONVERSION_DROP (today vs 7-day baseline)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        row_today_v = await db.execute_fetchall(
            "SELECT COUNT(DISTINCT person_id) as cnt FROM events WHERE store_id=? AND timestamp>=? AND event_type='ENTRY' AND is_staff=0",
            (store_id, today_start),
        )
        row_today_c = await db.execute_fetchall(
            "SELECT COUNT(DISTINCT person_id) as cnt FROM events WHERE store_id=? AND timestamp>=? AND zone_id='CASH_COUNTER' AND is_staff=0",
            (store_id, today_start),
        )
        today_visitors = row_today_v[0]["cnt"] if row_today_v else 0
        today_converted = row_today_c[0]["cnt"] if row_today_c else 0
        today_rate = today_converted / today_visitors if today_visitors > 0 else None

        seven_day_start = (now - timedelta(days=7)).isoformat()
        row_7d_v = await db.execute_fetchall(
            "SELECT COUNT(DISTINCT person_id) as cnt FROM events WHERE store_id=? AND timestamp>=? AND timestamp<? AND event_type='ENTRY' AND is_staff=0",
            (store_id, seven_day_start, today_start),
        )
        row_7d_c = await db.execute_fetchall(
            "SELECT COUNT(DISTINCT person_id) as cnt FROM events WHERE store_id=? AND timestamp>=? AND timestamp<? AND zone_id='CASH_COUNTER' AND is_staff=0",
            (store_id, seven_day_start, today_start),
        )
        hist_visitors = row_7d_v[0]["cnt"] if row_7d_v else 0
        hist_converted = row_7d_c[0]["cnt"] if row_7d_c else 0
        hist_rate = hist_converted / hist_visitors if hist_visitors > 0 else None

        if today_rate is not None and hist_rate is not None and hist_rate > 0:
            ratio = today_rate / hist_rate
            if ratio < CONV_CRITICAL_PCT:
                anomalies.append(Anomaly(
                    anomaly_id=str(uuid.uuid4()),
                    anomaly_type=AnomalyType.CONVERSION_DROP,
                    severity=Severity.CRITICAL,
                    zone_id=None, brand=None,
                    description=f"Conversion rate critically low: {today_rate:.1%} vs 7-day avg {hist_rate:.1%}",
                    metric_value=round(today_rate, 4),
                    threshold=round(hist_rate * CONV_CRITICAL_PCT, 4),
                    suggested_action="Investigate POS system, product availability, and staff engagement. Consider flash promotion.",
                    detected_at=now.isoformat(),
                ))
            elif ratio < CONV_WARN_PCT:
                anomalies.append(Anomaly(
                    anomaly_id=str(uuid.uuid4()),
                    anomaly_type=AnomalyType.CONVERSION_DROP,
                    severity=Severity.WARN,
                    zone_id=None, brand=None,
                    description=f"Conversion rate below average: {today_rate:.1%} vs 7-day avg {hist_rate:.1%}",
                    metric_value=round(today_rate, 4),
                    threshold=round(hist_rate * CONV_WARN_PCT, 4),
                    suggested_action="Beauty advisors should proactively engage browsing customers.",
                    detected_at=now.isoformat(),
                ))

        # 3. DEAD_ZONE detection
        dead_cutoff = (now - timedelta(minutes=DEAD_ZONE_MIN)).isoformat()
        brand_zones = [
            "EB_KOREAN","THE_FACE_SHOP","GOOD_VIBES","DERMDOC","MINIMALIST",
            "AQUALOGICA","LAKME_SKIN","MAYBELLINE","FACES_CANADA","LAKME",
            "COLORBAR_SUGAR","SWISS_BEAUTY","RENEE_NYBAE","ALPS_GOODNESS","STREAX",
        ]
        for zone_id in brand_zones:
            row = await db.execute_fetchall(
                "SELECT MAX(timestamp) as last_ts FROM events WHERE store_id=? AND zone_id=?",
                (store_id, zone_id),
            )
            last_ts = row[0]["last_ts"] if row else None
            if last_ts and last_ts < dead_cutoff:
                anomalies.append(Anomaly(
                    anomaly_id=str(uuid.uuid4()),
                    anomaly_type=AnomalyType.DEAD_ZONE,
                    severity=Severity.INFO,
                    zone_id=zone_id, brand=zone_id.replace("_", " ").title(),
                    description=f"{zone_id} has had no visitors for over {DEAD_ZONE_MIN} minutes",
                    metric_value=None, threshold=float(DEAD_ZONE_MIN),
                    suggested_action=f"Check if {zone_id} display is accessible. Consider repositioning promo material.",
                    detected_at=now.isoformat(),
                ))

        # 4. BRAND_DWELL_SPIKE — unique: brand zones with avg dwell >> overall avg
        row_avg = await db.execute_fetchall(
            "SELECT AVG(dwell_seconds) as avg_dwell FROM events WHERE store_id=? AND timestamp>=? AND dwell_seconds IS NOT NULL AND is_staff=0",
            (store_id, window_start),
        )
        overall_avg_dwell = row_avg[0]["avg_dwell"] if row_avg and row_avg[0]["avg_dwell"] else 0

        if overall_avg_dwell > 0:
            brand_dwell_rows = await db.execute_fetchall(
                """
                SELECT zone_id, AVG(dwell_seconds) as avg_d, COUNT(*) as cnt
                FROM events
                WHERE store_id=? AND timestamp>=? AND dwell_seconds IS NOT NULL
                AND zone_id NOT IN ('CASH_COUNTER','ENTRY','STAFF_AREA') AND is_staff=0
                GROUP BY zone_id HAVING cnt >= 3
                """,
                (store_id, window_start),
            )
            for br in brand_dwell_rows:
                if br["avg_d"] and br["avg_d"] > overall_avg_dwell * 2.0:
                    anomalies.append(Anomaly(
                        anomaly_id=str(uuid.uuid4()),
                        anomaly_type=AnomalyType.BRAND_DWELL_SPIKE,
                        severity=Severity.INFO,
                        zone_id=br["zone_id"],
                        brand=br["zone_id"].replace("_", " ").title(),
                        description=f"{br['zone_id']} avg dwell {br['avg_d']:.0f}s vs store avg {overall_avg_dwell:.0f}s — high interest signal",
                        metric_value=round(br["avg_d"], 1),
                        threshold=round(overall_avg_dwell * 2, 1),
                        suggested_action=f"Ensure {br['zone_id']} is fully stocked. Consider deploying a beauty advisor here.",
                        detected_at=now.isoformat(),
                    ))
    finally:
        await db.close()

    return AnomalyResponse(
        store_id=store_id,
        anomalies=anomalies,
        computed_at=now.isoformat(),
    )
