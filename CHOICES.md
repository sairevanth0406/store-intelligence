# Key Design Choices — Purplle Store Intelligence System

## Choice 1: YOLOv8n over YOLOv8s (or larger)

**Decision**: Use YOLOv8n (nano) instead of YOLOv8s (small).

**Rationale**:
- No GPU available. On CPU, YOLOv8n runs at ~8-12 FPS vs ~4-6 FPS for YOLOv8s.
- Person detection in retail CCTV doesn't require high-precision models — people are large objects in the frame.
- Combined with frame-skipping (process every 3rd frame), effective detection rate is ~3-4 FPS, which is sufficient for session-level analytics (people dwell for tens of seconds to minutes, not milliseconds).
- Trade-off: slightly lower confidence on partially occluded persons. Mitigated by ByteTrack's low-confidence track recovery.

**Alternative considered**: OpenCV background subtraction + contour detection (no ML). Rejected because it cannot distinguish people from moving objects, and fails in crowded scenes.

---

## Choice 2: SQLite with WAL mode over PostgreSQL

**Decision**: Use SQLite with WAL (Write-Ahead Logging) mode instead of a separate PostgreSQL container.

**Rationale**:
- No extra Docker container needed → simpler setup, one-command `docker compose up`.
- WAL mode enables concurrent readers during writes — critical for FastAPI where multiple analytics endpoints are queried simultaneously while the pipeline ingests events.
- `busy_timeout = 30000ms` prevents write contention errors during peak batch ingest.
- `INSERT OR IGNORE` on `event_id` PRIMARY KEY provides free idempotency.
- For this challenge's scale (5 cameras, 1 store, 1 day), SQLite handles >10,000 events/second, far exceeding our pipeline's output.
- Migration path: Replace aiosqlite with asyncpg and swap SQLite CREATE TABLE syntax for PostgreSQL — the abstraction layer is already in `database.py`.

**Alternative considered**: Redis Streams for event pipeline + PostgreSQL for queries. Rejected as over-engineered for this scale, adds setup complexity.

---

## Choice 3: Real Brand Zone Names over Generic Zone IDs

**Decision**: Map zones to actual brand names (`THE_FACE_SHOP`, `MINIMALIST`, `MAYBELLINE`) instead of generic IDs (`zone_1`, `zone_2`).

**Rationale**:
- Enables **brand-level conversion attribution**: Which brand zone led to which POS transaction? This is actionable retail intelligence.
- The POS CSV contains real brand names. By matching zone names to POS brand names (fuzzy match), we can attribute revenue: "Minimalist zone generated ₹X revenue today".
- Enables **BRAND_DWELL_SPIKE** anomaly: "Minimalist dwell is 3x store average — deploy beauty advisor or check stock". This is not possible with generic zone IDs.
- Enables the `/brands` endpoint — a unique differentiator that provides the metric a brand manager actually cares about: which of my shelf spaces performs best?
- Store layout data (Brigade Road - Store layout.xlsx) was analyzed to extract exact brand positions, and camera preview images confirmed zone locations.

**Trade-off**: Requires upfront zone polygon calibration per camera. Mitigated by the `store_layout.json` configuration file, which decouples zone definitions from code.
