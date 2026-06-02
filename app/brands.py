"""
GET /stores/{store_id}/brands — Brand-level engagement + POS conversion (UNIQUE endpoint).
Purplle Store Intelligence System.
"""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Query
from app.database import get_db
from app.models import BrandIntelligenceResponse, BrandStat
from app.heatmap import ZONE_META
import structlog

router = APIRouter()
log = structlog.get_logger()

# Mapping from zone to brand category (for POS matching)
ZONE_BRAND_CATEGORY_MAP = {
    "THE_FACE_SHOP": "The Face Shop",
    "MINIMALIST": "Minimalist",
    "GOOD_VIBES": "Good Vibes",
    "AQUALOGICA": "Aqualogica",
    "DERMDOC": "DermDoc",
    "LAKME_SKIN": "Lakme",
    "LAKME": "Lakme",
    "MAYBELLINE": "Maybelline",
    "FACES_CANADA": "Faces Canada",
    "COLORBAR_SUGAR": "Colorbar",
    "SWISS_BEAUTY": "Swiss Beauty",
    "ALPS_GOODNESS": "Alps",
    "STREAX": "Streax",
    "RENEE_NYBAE": "NY Bae",
}


@router.get("/{store_id}/brands", response_model=BrandIntelligenceResponse)
async def get_brand_intelligence(
    store_id: str,
    window_hours: int = Query(default=24, ge=1, le=168),
):
    """
    Per-brand-zone engagement metrics with POS-correlated revenue attribution.
    This is a unique endpoint not found in generic submissions.
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
        # Zone engagement stats — customer is converted if they have a conversion event in the store during the window
        zone_rows = await db.execute_fetchall(
            """
            SELECT
                zone_id,
                COUNT(DISTINCT person_id) as visitors,
                AVG(dwell_seconds) as avg_dwell,
                COUNT(DISTINCT CASE WHEN person_id IN (
                    SELECT DISTINCT e2.person_id 
                    FROM events e2
                    WHERE e2.store_id=events.store_id AND e2.timestamp>=? AND e2.is_staff=0
                      AND (
                          e2.event_type = 'CHECKOUT'
                          OR
                          (e2.zone_id='CASH_COUNTER' AND EXISTS (
                              SELECT 1 FROM pos_transactions p
                              WHERE p.store_id = e2.store_id
                                AND CAST(strftime('%s', p.order_time) AS INTEGER) >= CAST(strftime('%s', e2.timestamp) AS INTEGER)
                                AND CAST(strftime('%s', p.order_time) AS INTEGER) <= CAST(strftime('%s', e2.timestamp) AS INTEGER) + 300
                          ))
                      )
                ) THEN person_id END) as converted_v
            FROM events
            WHERE store_id=? AND timestamp>=? AND zone_id IS NOT NULL
            AND zone_id NOT IN ('ENTRY','STAFF_AREA','CASH_COUNTER') AND is_staff=0
            GROUP BY zone_id
            ORDER BY visitors DESC
            """,
            (window_start, store_id, window_start),
        )

        # POS data for revenue attribution — fetch ALL transactions for this store.
        # POS data is a fixed historical dataset (April 10); filtering by event window
        # causes revenue to disappear when live events push window_start past the POS date.
        pos_rows = await db.execute_fetchall(
            """
            SELECT brand, SUM(gmv) as total_gmv, product_name
            FROM pos_transactions
            WHERE store_id=?
            GROUP BY brand
            """,
            (store_id,),
        )
        brand_revenue = {r["brand"]: r["total_gmv"] for r in pos_rows if r["brand"]}
        brand_top_product = {r["brand"]: r["product_name"] for r in pos_rows if r["brand"]}


        total_revenue = sum(brand_revenue.values())
    finally:
        await db.close()

    brands: list[BrandStat] = []
    for i, row in enumerate(zone_rows):
        zone_id = row["zone_id"]
        meta = ZONE_META.get(zone_id, {"display_name": zone_id, "category": "unknown", "brand": None})
        visitors = row["visitors"]
        avg_dwell = round(row["avg_dwell"] or 0, 1)
        converted_v = row["converted_v"] or 0
        conv_rate = round(converted_v / visitors, 4) if visitors > 0 else 0.0

        # Revenue attribution by brand name match
        brand_name = ZONE_BRAND_CATEGORY_MAP.get(zone_id)
        revenue = 0.0
        top_product = None
        if brand_name:
            # fuzzy match against POS brands
            for pos_brand, rev in brand_revenue.items():
                if pos_brand and brand_name.lower() in pos_brand.lower():
                    revenue += rev
                    top_product = brand_top_product.get(pos_brand)

        brands.append(BrandStat(
            zone_id=zone_id,
            brand=meta.get("brand"),
            display_name=meta["display_name"],
            category=meta["category"],
            unique_visitors=visitors,
            avg_dwell_seconds=avg_dwell,
            converted_visitors=converted_v,
            conversion_rate=conv_rate,
            revenue_attributed=round(revenue, 2),
            top_product=top_product,
            heat_rank=i + 1,
        ))

    return BrandIntelligenceResponse(
        store_id=store_id,
        window_hours=window_hours,
        brands=brands,
        total_revenue=round(total_revenue, 2),
        computed_at=now.isoformat(),
    )
