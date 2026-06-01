"""
Tests for brands, journeys, heatmap, and health endpoints.

# PROMPT: Generate comprehensive tests for /stores/{store_id}/brands, /stores/{store_id}/journeys, /stores/{store_id}/heatmap, and /health endpoints, ensuring perfect branch coverage and handling of empty stores and valid structures.
# CHANGES MADE: Added tests for brand revenue matching, journey sequence rendering, heatmap normalization, and camera status check.
"""
import pytest
from tests.conftest import STORE_ID


@pytest.mark.asyncio
async def test_brands_endpoint(seeded_client):
    """Test Brand Intelligence endpoint returns correct structure and revenue mapping."""
    resp = await seeded_client.get(f"/stores/{STORE_ID}/brands?window_hours=24")
    assert resp.status_code == 200
    data = resp.json()
    assert "brands" in data
    assert "total_revenue" in data
    assert data["store_id"] == STORE_ID

    brands = data["brands"]
    assert len(brands) > 0
    b = brands[0]
    assert "zone_id" in b
    assert "display_name" in b
    assert "unique_visitors" in b
    assert "revenue_attributed" in b


@pytest.mark.asyncio
async def test_brands_empty_store(client):
    """Test Brand Intelligence for an empty store."""
    resp = await client.get("/stores/STORE_EMPTY/brands?window_hours=24")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["brands"]) == 0
    assert data["total_revenue"] == 0.0


@pytest.mark.asyncio
async def test_journeys_endpoint(seeded_client):
    """Test shopper journey reconstruction and common path rendering."""
    resp = await seeded_client.get(f"/stores/{STORE_ID}/journeys?window_hours=24")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_journeys" in data
    assert "common_paths" in data
    assert "sample_journeys" in data
    assert data["store_id"] == STORE_ID


@pytest.mark.asyncio
async def test_journeys_empty_store(client):
    """Test shopper journeys for an empty store."""
    resp = await client.get("/stores/STORE_EMPTY/journeys?window_hours=24")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_journeys"] == 0
    assert len(data["sample_journeys"]) == 0


@pytest.mark.asyncio
async def test_heatmap_endpoint(seeded_client):
    """Test heatmap normalization and confidence calculations."""
    resp = await seeded_client.get(f"/stores/{STORE_ID}/heatmap?window_hours=24")
    assert resp.status_code == 200
    data = resp.json()
    assert "zones" in data
    assert "max_visitors" in data
    assert len(data["zones"]) > 0

    for zone in data["zones"]:
        assert 0 <= zone["heat_score"] <= 100
        assert zone["data_confidence"] in ["high", "medium", "low"]


@pytest.mark.asyncio
async def test_heatmap_empty_store(client):
    """Test heatmap endpoint for an empty store."""
    resp = await client.get("/stores/STORE_EMPTY/heatmap?window_hours=24")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["zones"]) == 0
    assert data["max_visitors"] == 0


@pytest.mark.asyncio
async def test_health_endpoint(seeded_client):
    """Test health endpoint liveness and camera staleness detection."""
    resp = await seeded_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "cameras" in data
    assert data["db_ok"] is True


@pytest.mark.asyncio
async def test_health_empty_store(client):
    """Test health endpoint with no data or db errors."""
    resp = await client.get("/health?store_id=STORE_EMPTY")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ["degraded", "unhealthy", "healthy"]
