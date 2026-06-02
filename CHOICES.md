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

---

## Choice 4: Redis Streams over Kafka for Event Transport

**Decision**: Use Redis Streams (with automatic HTTP fallback) instead of Apache Kafka for buffering events from the CV pipeline to the API.

**Rationale**:
- **Durability over raw HTTP**: Previously, the pipeline sent events via synchronous HTTP POST directly to FastAPI. If the API was briefly unavailable, events were **permanently lost** after 3 retries. Redis Streams gives us a durable, append-only event log — events survive API restarts and are ACK-only removed from the stream once successfully ingested.
- **Redis vs. Kafka**: Kafka is the industry standard for high-throughput event streaming but adds significant operational complexity (ZooKeeper/KRaft quorum, topic partitioning, broker management). For a single store with 5 cameras producing ~100 events/minute, Redis Streams provides equivalent durability with a fraction of the setup cost. Redis 7's `maxlen` with approximate trimming acts as a circular buffer, capping memory usage at ~256MB.
- **Graceful fallback**: The `EventEmitter` tries to connect to Redis at startup. If Redis is unreachable (e.g., running without Docker), it silently falls back to direct HTTP POST — preserving backwards compatibility and making local development dependency-free.
- **AI suggestion**: AI initially suggested Kafka with a consumer group and topic partitioning. We overrode this in favour of Redis Streams for this scale because Kafka's operational overhead (multi-broker, topic management) would overwhelm the single-store challenge context without adding meaningful value.

**Alternative considered**: Apache Kafka. Rejected for this scale as over-engineered. PostgreSQL LISTEN/NOTIFY was also considered but couples event transport to the analytics DB.

---

## Choice 5: httpx + ThreadPoolExecutor over blocking requests

**Decision**: Replace the synchronous `requests` library in the event emitter with `httpx` running inside a `concurrent.futures.ThreadPoolExecutor`.

**Rationale**:
- **Non-blocking camera pipelines**: The original emitter used Python's `requests` library synchronously. When 5 cameras were processing frames simultaneously in a multi-threaded environment, each camera's detection loop would stall for up to 30 seconds waiting for an HTTP response before processing the next frame — causing cascading frame drops.
- **httpx advantages**: `httpx` is a modern HTTP client with connection pooling, HTTP/2 support, and cleaner timeout semantics. It performs measurably better than `requests` for repeated connections to the same host (our FastAPI instance).
- **ThreadPoolExecutor**: By submitting each batch send to a thread pool (`max_workers=4`), the main detection loop immediately returns after calling `flush()`, continues processing the next video frame, and the HTTP call completes asynchronously in a background thread. The `drain()` method at pipeline shutdown gracefully waits for all in-flight requests.
- **AI suggestion**: AI suggested using `asyncio` with `httpx.AsyncClient` throughout. We partially overrode this — the detection loop itself is synchronous (driven by OpenCV's frame-by-frame API which cannot be awaited), so we chose a ThreadPoolExecutor hybrid that achieves the same non-blocking property without restructuring the entire pipeline as async.

