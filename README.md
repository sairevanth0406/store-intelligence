# Purplle Store Intelligence System
> **Purplle Tech Challenge 2026, Round 2** — Brigade Road, Bangalore

An end-to-end retail intelligence platform that converts raw CCTV footage into actionable store insights using computer vision and real-time analytics.

---

## ⚡ Quick Start (5 commands)

```bash
# 1. Clone / enter the directory
cd store-intelligence

# 2. Start the API (Docker)
docker compose up -d

# 3. Load POS data + run pipeline (demo mode — no GPU needed)
bash pipeline/run.sh "../cctv_footage/CCTV Footage" STORE_BLR_002 --demo

# 4. Run tests with coverage
pip install -r requirements.txt
pytest tests/ --cov=app

# 5. Open live dashboard
open http://localhost:8000/dashboard
```

> For real video processing (with YOLOv8): `pip install ultralytics` then remove `--demo`

---

## 🏗️ Architecture

```
CCTV Clips (5 cameras)
     │
     ▼
 ┌──────────────────────────────────────┐
 │  Detection Pipeline (CPU-optimized)  │
 │  YOLOv8n + ByteTrack per camera      │
 │  Real brand zone mapping (Shapely)   │
 │  Staff detection heuristics          │
 │  Session lifecycle tracking          │
 └────────────┬─────────────────────────┘
              │ POST /events/ingest
              ▼
 ┌──────────────────────────────────────┐
 │  FastAPI Application                 │
 │  /events/ingest    (batch, idempotent│
 │  /stores/{id}/metrics                │
 │  /stores/{id}/funnel                 │
 │  /stores/{id}/heatmap                │
 │  /stores/{id}/anomalies              │
 │  /stores/{id}/brands  ← UNIQUE       │
 │  /stores/{id}/journeys ← UNIQUE      │
 │  /health                             │
 └────────────┬─────────────────────────┘
              │
              ▼
 ┌──────────────────────────────────────┐
 │  SQLite (WAL mode) + aiosqlite       │
 │  events, sessions, pos_transactions  │
 │  brand_engagements                   │
 └──────────────────────────────────────┘
              │
              ▼
 ┌──────────────────────────────────────┐
 │  Live Web Dashboard                  │
 │  SVG floor plan heatmap              │
 │  Real-time funnel chart              │
 │  Brand performance leaderboard       │
 │  Anomaly feed with toasts            │
 │  Auto-refresh every 3 seconds        │
 └──────────────────────────────────────┘
```

---

## 🌟 What Makes This Unique

| Feature | Generic Submissions | This System |
|---|---|---|
| **Zone naming** | zone_1, zone_2 | Real brand names: `THE_FACE_SHOP`, `MINIMALIST`, `MAYBELLINE` |
| **Dashboard** | Terminal table | Full web UI with SVG floor plan heatmap |
| **POS correlation** | Time window | Brand-level: which zone drove which brand's sale |
| **Salesperson data** | Not used | Named attribution (kasthuri, Zufishan, etc.) |
| **Anomalies** | Generic thresholds | `BRAND_DWELL_SPIKE` — restock opportunity signal |
| **Journeys** | None | Multi-camera path reconstruction + common path analysis |
| **Staff detection** | Colour heuristic | Camera + zone persistence heuristics |

---

## 📡 API Reference

### `POST /events/ingest`
Batch ingest up to 500 events. Idempotent on `event_id`.
```json
{
  "events": [
    {
      "event_id": "uuid",
      "store_id": "STORE_BLR_002",
      "camera_id": "CAM1",
      "event_type": "ZONE_ENTER",
      "person_id": "CAM1_42_a3f7",
      "is_staff": false,
      "zone_id": "THE_FACE_SHOP",
      "timestamp": "2026-04-10T14:45:00+00:00",
      "dwell_seconds": null,
      "confidence": 0.92
    }
  ]
}
```

### `GET /stores/STORE_BLR_002/metrics?window_hours=24`
Returns: `unique_visitors`, `conversion_rate`, `avg_dwell_seconds`, `queue_depth`, `abandonment_rate`, `top_zones`

### `GET /stores/STORE_BLR_002/funnel?window_hours=24`
5-stage funnel: Entry → Browse → Deep Browse (30s+) → Billing Intent → Purchase

### `GET /stores/STORE_BLR_002/heatmap?window_hours=24`
Per-zone heat scores (0-100), visitor counts, avg dwell, data_confidence flag

### `GET /stores/STORE_BLR_002/anomalies?window_hours=1`
Types: `BILLING_QUEUE_SPIKE`, `CONVERSION_DROP`, `DEAD_ZONE`, `BRAND_DWELL_SPIKE`
All with `severity` (INFO/WARN/CRITICAL) and `suggested_action`

### `GET /stores/STORE_BLR_002/brands?window_hours=24` ← UNIQUE
Per-brand-zone engagement with POS revenue attribution

### `GET /stores/STORE_BLR_002/journeys?window_hours=24` ← UNIQUE
Shopper journey reconstruction + common path analysis

### `GET /health`
Per-camera staleness check. Returns STALE_FEED warning if any camera silent >10 min.

---

## 🗂️ Project Structure

```
store-intelligence/
├── pipeline/
│   ├── detect.py      # YOLOv8n + ByteTrack inference
│   ├── zones.py       # Brand zone polygon mapper
│   ├── tracker.py     # Session lifecycle
│   ├── staff.py       # Staff heuristics
│   ├── emit.py        # Batch event emitter
│   ├── pos_loader.py  # POS CSV ingestion
│   └── run.sh         # One-command pipeline runner
├── app/
│   ├── main.py        # FastAPI app + dashboard mount
│   ├── models.py      # Pydantic v2 schemas
│   ├── database.py    # Async SQLite (WAL mode)
│   ├── ingestion.py   # POST /events/ingest
│   ├── metrics.py     # Store KPIs
│   ├── funnel.py      # Conversion funnel
│   ├── heatmap.py     # Zone heatmap
│   ├── anomalies.py   # Anomaly detection
│   ├── brands.py      # Brand intelligence
│   ├── journeys.py    # Journey reconstruction
│   ├── health.py      # Health check
│   └── logging_config.py
├── dashboard/
│   ├── index.html     # Web dashboard
│   ├── style.css      # Premium dark UI
│   └── app.js         # Live polling + charts
├── tests/
│   ├── conftest.py
│   ├── test_ingestion.py
│   ├── test_metrics.py
│   ├── test_funnel.py
│   └── test_anomalies.py
├── data/
│   └── store_layout.json  # Real brand zone polygons
├── docs/
│   ├── DESIGN.md
│   └── CHOICES.md
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── pytest.ini
```

---

## 🏪 Store Zones (Brigade Road, Bangalore)

### Back Wall — Skincare
`EB_KOREAN` · `THE_FACE_SHOP` · `GOOD_VIBES` · `DERMDOC` · `MINIMALIST` · `AQUALOGICA` · `LAKME_SKIN` · `ACCESSORIES`

### Front Wall — Makeup & Hair
`MAYBELLINE` · `FACES_CANADA` · `LAKME` · `COLORBAR_SUGAR` · `SWISS_BEAUTY` · `RENEE_NYBAE` · `ALPS_GOODNESS` · `STREAX`

### Centre Floor
`FRAGRANCE` · `NAIL_UNIT` · `MAKEUP_UNIT`

### Special
`CASH_COUNTER` (billing) · `PMU` · `ENTRY` · `STAFF_AREA`

---

## 🧪 Testing

```bash
pytest tests/ -v --cov=app --cov-report=term-missing
```

Coverage gate: **70%** (enforced in `pytest.ini`)

Test suite covers:
- ✅ Idempotent ingest (event_id deduplication)
- ✅ Partial success (per-event error reporting)
- ✅ Batch size limit (>500 → 422)
- ✅ Staff exclusion from visitor metrics
- ✅ Anti-hardcoding: metrics change when data changes
- ✅ Funnel monotonicity
- ✅ BILLING_QUEUE_SPIKE detection
- ✅ BRAND_DWELL_SPIKE detection (unique feature)
- ✅ Empty store edge cases

---

## ⚙️ Configuration

All anomaly thresholds are environment-variable configurable:

| Variable | Default | Description |
|---|---|---|
| `DB_PATH` | `/data/store_intelligence.db` | SQLite path |
| `QUEUE_SPIKE_WARN` | `3` | Queue warn threshold |
| `QUEUE_SPIKE_CRITICAL` | `6` | Queue critical threshold |
| `CONV_DROP_WARN` | `0.80` | Conversion drop warn (80% of 7-day avg) |
| `CONV_DROP_CRITICAL` | `0.60` | Conversion drop critical (60% of 7-day avg) |
| `DEAD_ZONE_MINUTES` | `30` | Dead zone detection window |
| `API_URL` | `http://localhost:8000` | API endpoint for pipeline |
| `EMIT_BATCH_SIZE` | `100` | Events per API call |

---

## 📊 Dashboard

Open **http://localhost:8000/dashboard** after starting the API.

Features:
- 🗺️ **SVG Store Floor Plan** — real Brigade Road layout with live zone highlighting
- 📊 **KPI Cards** — visitors, conversion, dwell, queue, abandonment
- 🔽 **Conversion Funnel** — animated 5-stage bar chart
- ⚠️ **Anomaly Feed** — live alerts with toast notifications for CRITICAL
- 🏆 **Brand Leaderboard** — per-brand visitors, dwell, conversions, revenue
- 🗺️ **Shopper Paths** — most common zone traversal patterns
- Auto-refreshes every **3 seconds**
