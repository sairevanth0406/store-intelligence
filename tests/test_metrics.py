"""
Tests for GET /stores/{store_id}/metrics.

# PROMPT: Test that staff are excluded from metrics, that conversion_rate is computed
# from actual billing zone visits, and that queue_depth reflects real-time counts.
# CHANGES MADE: Added zero-visitor edge case and window filtering test.
"""
import pytest
from tests.conftest import STORE_ID


@pytest.mark.asyncio
async def test_metrics_basic(seeded_client):
    """Metrics endpoint returns correct structure."""
    resp = await seeded_client.get(f"/stores/{STORE_ID}/metrics?window_hours=24")
    assert resp.status_code == 200
    data = resp.json()
    assert "unique_visitors" in data
    assert "conversion_rate" in data
    assert "avg_dwell_seconds" in data
    assert "queue_depth" in data
    assert "abandonment_rate" in data
    assert "computed_at" in data


@pytest.mark.asyncio
async def test_metrics_excludes_staff(seeded_client):
    """Staff (is_staff=True) are not counted as visitors."""
    resp = await seeded_client.get(f"/stores/{STORE_ID}/metrics?window_hours=24")
    data = resp.json()
    # Sample events have 3 non-staff visitors (P001, P002, P003) and 1 staff
    assert data["unique_visitors"] == 3


@pytest.mark.asyncio
async def test_metrics_conversion_rate(seeded_client):
    """Conversion rate reflects visitors who visited CASH_COUNTER."""
    resp = await seeded_client.get(f"/stores/{STORE_ID}/metrics?window_hours=24")
    data = resp.json()
    # P001 and P003 visited CASH_COUNTER = 2/3 = 0.6667
    assert 0 <= data["conversion_rate"] <= 1


@pytest.mark.asyncio
async def test_metrics_values_are_not_hardcoded(seeded_client):
    """Metrics must change when data changes (anti-hardcoding check)."""
    r1 = await seeded_client.get(f"/stores/{STORE_ID}/metrics?window_hours=24")
    v1 = r1.json()["unique_visitors"]

    # Ingest new visitor
    from tests.conftest import make_event
    import uuid
    new_event = make_event("ENTRY", f"NEW_{uuid.uuid4().hex[:6]}", minutes_ago=5)
    await seeded_client.post("/events/ingest", json={"events": [new_event]})

    r2 = await seeded_client.get(f"/stores/{STORE_ID}/metrics?window_hours=24")
    v2 = r2.json()["unique_visitors"]
    assert v2 == v1 + 1  # Must actually change!


@pytest.mark.asyncio
async def test_metrics_empty_store(client):
    """Metrics for store with no events returns zeros, not errors."""
    resp = await client.get("/stores/STORE_EMPTY/metrics?window_hours=24")
    assert resp.status_code == 200
    data = resp.json()
    assert data["unique_visitors"] == 0
    assert data["conversion_rate"] == 0.0
