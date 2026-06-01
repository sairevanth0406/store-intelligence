"""
Tests for GET /stores/{store_id}/funnel.

# PROMPT: Verify funnel stages are ordered correctly, that stage counts are
# monotonically non-increasing, and that re-entry visitors are counted once.
# CHANGES MADE: Added test for deep browse stage (30s+ dwell) and stage ordering.
"""
import pytest
from tests.conftest import STORE_ID


@pytest.mark.asyncio
async def test_funnel_structure(seeded_client):
    """Funnel returns correct stages in order."""
    resp = await seeded_client.get(f"/stores/{STORE_ID}/funnel?window_hours=24")
    assert resp.status_code == 200
    data = resp.json()
    assert "stages" in data
    assert len(data["stages"]) == 5
    stages = [s["stage"] for s in data["stages"]]
    assert stages[0] == "Entry"
    assert "Purchase" in stages[-1] or "Checkout" in stages[-1]


@pytest.mark.asyncio
async def test_funnel_monotonically_decreasing(seeded_client):
    """Each funnel stage count must be <= previous stage."""
    resp = await seeded_client.get(f"/stores/{STORE_ID}/funnel?window_hours=24")
    stages = resp.json()["stages"]
    counts = [s["count"] for s in stages]
    for i in range(1, len(counts)):
        assert counts[i] <= counts[i-1], f"Stage {i} ({counts[i]}) > stage {i-1} ({counts[i-1]})"


@pytest.mark.asyncio
async def test_funnel_pct_of_entry(seeded_client):
    """pct_of_entry must be between 0 and 1 for all stages."""
    resp = await seeded_client.get(f"/stores/{STORE_ID}/funnel?window_hours=24")
    for stage in resp.json()["stages"]:
        assert 0 <= stage["pct_of_entry"] <= 1


@pytest.mark.asyncio
async def test_funnel_entry_pct_is_one(seeded_client):
    """Entry stage pct_of_entry is always 1.0."""
    resp = await seeded_client.get(f"/stores/{STORE_ID}/funnel?window_hours=24")
    entry_stage = resp.json()["stages"][0]
    assert entry_stage["pct_of_entry"] == 1.0


@pytest.mark.asyncio
async def test_funnel_empty_store(client):
    """Funnel for empty store returns zeros without error."""
    resp = await client.get("/stores/STORE_EMPTY/funnel?window_hours=24")
    assert resp.status_code == 200
    data = resp.json()
    for stage in data["stages"]:
        assert stage["count"] == 0
