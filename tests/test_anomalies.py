"""
Tests for GET /stores/{store_id}/anomalies.

# PROMPT: Test BILLING_QUEUE_SPIKE triggers above threshold, DEAD_ZONE detects
# zones with no recent events, and BRAND_DWELL_SPIKE fires on high-dwell brands.
# CHANGES MADE: Added brand dwell spike test unique to this submission.
"""
import uuid
import pytest
from datetime import datetime, timezone, timedelta
from tests.conftest import make_event, STORE_ID


@pytest.mark.asyncio
async def test_anomalies_endpoint_returns_list(seeded_client):
    """Anomalies endpoint returns a list (possibly empty)."""
    resp = await seeded_client.get(f"/stores/{STORE_ID}/anomalies?window_hours=1")
    assert resp.status_code == 200
    data = resp.json()
    assert "anomalies" in data
    assert isinstance(data["anomalies"], list)
    assert "computed_at" in data


@pytest.mark.asyncio
async def test_billing_queue_spike(client):
    """BILLING_QUEUE_SPIKE fires when queue depth exceeds threshold."""
    # Flood billing queue: 7 ZONE_ENTER with no ZONE_EXIT
    events = []
    for i in range(7):
        events.append(make_event("ZONE_ENTER", f"QP{i}", "CASH_COUNTER", minutes_ago=5))
    await client.post("/events/ingest", json={"events": events})

    resp = await client.get(f"/stores/{STORE_ID}/anomalies?window_hours=1")
    data = resp.json()
    types = [a["anomaly_type"] for a in data["anomalies"]]
    assert "BILLING_QUEUE_SPIKE" in types

    # Verify severity
    spike = next(a for a in data["anomalies"] if a["anomaly_type"] == "BILLING_QUEUE_SPIKE")
    assert spike["severity"] in ("WARN", "CRITICAL")
    assert spike["suggested_action"]


@pytest.mark.asyncio
async def test_anomaly_structure(seeded_client):
    """Each anomaly has required fields."""
    resp = await seeded_client.get(f"/stores/{STORE_ID}/anomalies?window_hours=24")
    for a in resp.json()["anomalies"]:
        assert "anomaly_id" in a
        assert "anomaly_type" in a
        assert "severity" in a
        assert "description" in a
        assert "suggested_action" in a
        assert "detected_at" in a


@pytest.mark.asyncio
async def test_brand_dwell_spike(client):
    """BRAND_DWELL_SPIKE fires for brand zone with unusually high dwell."""
    # Create very high dwell events for MINIMALIST (unique feature)
    events = [
        make_event("DWELL", f"BD{i}", "MINIMALIST", dwell_seconds=600, minutes_ago=30)
        for i in range(5)
    ]
    # Add low-dwell baseline for other zones
    events += [
        make_event("DWELL", f"LOW{i}", "GOOD_VIBES", dwell_seconds=15, minutes_ago=30)
        for i in range(10)
    ]
    await client.post("/events/ingest", json={"events": events})

    resp = await client.get(f"/stores/{STORE_ID}/anomalies?window_hours=1")
    types = [a["anomaly_type"] for a in resp.json()["anomalies"]]
    assert "BRAND_DWELL_SPIKE" in types


@pytest.mark.asyncio
async def test_anomalies_for_empty_store(client):
    """Anomaly endpoint returns empty list for store with no events."""
    resp = await client.get("/stores/STORE_EMPTY/anomalies?window_hours=1")
    assert resp.status_code == 200
    assert resp.json()["anomalies"] == []
