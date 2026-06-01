"""
Shared test fixtures for Purplle Store Intelligence System.

# PROMPT: Create a shared test DB fixture with sample events covering all event types.
# CHANGES MADE: Added fixtures for brand zones, POS transactions, and multiple cameras.
# Uses a temp file path per test to ensure isolation (aiosqlite :memory: creates
# separate databases per connection, which breaks multi-call tests).
"""
import pytest
import pytest_asyncio
import uuid
import tempfile
import os
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport

STORE_ID = "STORE_BLR_002"


def make_event(event_type, person_id="P001", zone_id=None, is_staff=False,
               camera_id="CAM1", dwell_seconds=None, minutes_ago=30):
    ts = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return {
        "event_id": str(uuid.uuid4()),
        "store_id": STORE_ID,
        "camera_id": camera_id,
        "event_type": event_type,
        "person_id": person_id,
        "is_staff": is_staff,
        "zone_id": zone_id,
        "timestamp": ts.isoformat(),
        "dwell_seconds": dwell_seconds,
        "confidence": 0.9,
    }


SAMPLE_EVENTS = [
    # Visitor 1: browses skincare, converts
    make_event("ENTRY", "P001", minutes_ago=90),
    make_event("ZONE_ENTER", "P001", "THE_FACE_SHOP", minutes_ago=85),
    make_event("DWELL", "P001", "THE_FACE_SHOP", dwell_seconds=120, minutes_ago=83),
    make_event("ZONE_ENTER", "P001", "MINIMALIST", minutes_ago=80),
    make_event("DWELL", "P001", "MINIMALIST", dwell_seconds=90, minutes_ago=78),
    make_event("ZONE_ENTER", "P001", "CASH_COUNTER", minutes_ago=70),
    make_event("CHECKOUT", "P001", "CASH_COUNTER", minutes_ago=68),
    make_event("EXIT", "P001", minutes_ago=65),
    # Visitor 2: browses makeup, no conversion
    make_event("ENTRY", "P002", minutes_ago=60),
    make_event("ZONE_ENTER", "P002", "MAYBELLINE", minutes_ago=55, camera_id="CAM2"),
    make_event("DWELL", "P002", "MAYBELLINE", dwell_seconds=45, minutes_ago=53, camera_id="CAM2"),
    make_event("EXIT", "P002", minutes_ago=50),
    # Staff: should be excluded from metrics
    make_event("ENTRY", "STAFF01", is_staff=True, camera_id="CAM4", minutes_ago=120),
    make_event("ZONE_ENTER", "STAFF01", "STAFF_AREA", is_staff=True, camera_id="CAM4", minutes_ago=119),
    # Visitor 3: billing queue
    make_event("ENTRY", "P003", minutes_ago=20),
    make_event("ZONE_ENTER", "P003", "CASH_COUNTER", minutes_ago=10),
]


@pytest_asyncio.fixture
async def client(tmp_path):
    """Client with a fresh temp-file SQLite DB per test."""
    db_file = str(tmp_path / "test.db")
    os.environ["DB_PATH"] = db_file

    # Re-import database module to pick up new DB_PATH
    import importlib
    import app.database as db_module
    db_module.DB_PATH = db_file

    from app.database import init_db
    from app.main import app

    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def seeded_client(client):
    """Client with sample events already ingested."""
    resp = await client.post("/events/ingest", json={"events": SAMPLE_EVENTS})
    assert resp.status_code == 200
    return client

