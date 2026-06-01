"""
POS transaction loader — parses Brigade Road POS CSV and inserts into DB.
Enables brand-level conversion attribution.
Purplle Store Intelligence System.
"""
import csv
import uuid
import aiosqlite
from datetime import datetime, timezone
from pathlib import Path
import structlog

log = structlog.get_logger()

STORE_ID = "STORE_BLR_002"


def parse_pos_csv(filepath: str) -> list[dict]:
    """
    Parse the Brigade Road POS CSV.
    Columns (from actual file): order_id, order_time, GMV, NMV,
    product_name, brand, category, salesperson_id, ...
    """
    transactions = []
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Normalize keys (strip whitespace)
            row = {k.strip(): v.strip() for k, v in row.items()}

            # Flexible column name handling
            order_id = (
                row.get("order_id") or
                row.get("Order ID") or
                row.get("OrderID") or
                str(uuid.uuid4())
            )
            order_date_raw = row.get("order_date") or row.get("Order Date") or ""
            order_time_raw = row.get("order_time") or row.get("Order Time") or row.get("Date") or ""
            if order_date_raw and order_time_raw:
                order_time_combined = f"{order_date_raw.strip()} {order_time_raw.strip()}"
            else:
                order_time_combined = order_time_raw or order_date_raw

            # Try to parse datetime
            order_time = _parse_datetime(order_time_combined)

            gmv = _float(row.get("GMV") or row.get("gmv") or row.get("Amount") or "0")
            nmv = _float(row.get("NMV") or row.get("nmv") or "0")
            product = row.get("product_name") or row.get("Product Name") or row.get("Product") or ""
            brand = row.get("brand_name") or row.get("brand") or row.get("Brand") or ""
            category = row.get("dep_name") or row.get("category") or row.get("Category") or ""
            salesperson = (
                row.get("salesperson_id") or
                row.get("Salesperson") or
                row.get("salesperson_name") or ""
            )

            transactions.append({
                "order_id": order_id,
                "store_id": STORE_ID,
                "order_time": order_time,
                "gmv": gmv,
                "nmv": nmv,
                "product_name": product,
                "brand": brand,
                "category": category,
                "salesperson_id": salesperson,
            })

    log.info("pos_loader.parsed", count=len(transactions), filepath=filepath)
    return transactions


def _parse_datetime(raw: str) -> str:
    """Try multiple date formats, return ISO string."""
    formats = [
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%m/%d/%Y %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%d-%m-%Y",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(raw.strip(), fmt)
            return dt.replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    return raw  # Return as-is if parse fails


def _float(v: str) -> float:
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0


async def load_pos_to_db(filepath: str, db_path: str):
    """Load POS transactions into database."""
    transactions = parse_pos_csv(filepath)
    async with aiosqlite.connect(db_path) as db:
        for t in transactions:
            await db.execute(
                """
                INSERT OR REPLACE INTO pos_transactions
                    (order_id, store_id, order_time, gmv, nmv, product_name, brand, category, salesperson_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (t["order_id"], t["store_id"], t["order_time"],
                 t["gmv"], t["nmv"], t["product_name"],
                 t["brand"], t["category"], t["salesperson_id"]),
            )
        await db.commit()
    log.info("pos_loader.loaded_to_db", count=len(transactions))
