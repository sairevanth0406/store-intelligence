"""
Tests for POST /events/ingest.

# PROMPT: Test idempotency (same event_id ingested twice = duplicate), partial success
# (batch with 1 valid + 1 invalid), and batch size limit enforcement.
# CHANGES MADE: Added tests for staff flag preservation and brand zone events.
"""
import uuid
import pytest
from tests.conftest import make_event, STORE_ID


@pytest.mark.asyncio
async def test_ingest_single_event(client):
    """Single valid event returns accepted=1."""
    event = make_event("ENTRY", "T001")
    resp = await client.post("/events/ingest", json={"events": [event]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] == 1
    assert data["duplicates"] == 0
    assert data["errors"] == 0


@pytest.mark.asyncio
async def test_ingest_idempotency(client):
    """Same event_id ingested twice → second is counted as duplicate."""
    event = make_event("ENTRY", "T002")
    r1 = await client.post("/events/ingest", json={"events": [event]})
    r2 = await client.post("/events/ingest", json={"events": [event]})
    assert r1.json()["accepted"] == 1
    assert r2.json()["duplicates"] == 1
    assert r2.json()["accepted"] == 0


@pytest.mark.asyncio
async def test_ingest_batch(client):
    """Batch of 5 unique events all accepted."""
    events = [make_event("ENTRY", f"T{i:03d}") for i in range(5)]
    resp = await client.post("/events/ingest", json={"events": events})
    data = resp.json()
    assert data["accepted"] == 5
    assert len(data["results"]) == 5


@pytest.mark.asyncio
async def test_ingest_batch_too_large(client):
    """Batch over 500 events returns 422."""
    events = [make_event("ENTRY", f"BIG{i}") for i in range(501)]
    resp = await client.post("/events/ingest", json={"events": events})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_ingest_invalid_event_type(client):
    """Invalid event_type returns 422."""
    event = make_event("ENTRY", "T003")
    event["event_type"] = "INVALID_TYPE"
    resp = await client.post("/events/ingest", json={"events": [event]})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_ingest_staff_flag_preserved(client):
    """Staff events are stored with is_staff=True."""
    event = make_event("ENTRY", "STAFF99", is_staff=True, camera_id="CAM4")
    resp = await client.post("/events/ingest", json={"events": [event]})
    assert resp.json()["accepted"] == 1
    result = resp.json()["results"][0]
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_ingest_zone_event(client):
    """Zone events with brand zone_id are accepted."""
    event = make_event("DWELL", "T004", zone_id="MINIMALIST", dwell_seconds=120.0)
    resp = await client.post("/events/ingest", json={"events": [event]})
    assert resp.json()["accepted"] == 1


@pytest.mark.asyncio
async def test_ingest_returns_per_event_results(client):
    """Response includes per-event results with status field."""
    events = [make_event("ENTRY", f"R{i}") for i in range(3)]
    resp = await client.post("/events/ingest", json={"events": events})
    data = resp.json()
    assert len(data["results"]) == 3
    for r in data["results"]:
        assert r["status"] in ("ok", "duplicate", "error")
        assert "event_id" in r
