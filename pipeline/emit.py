"""
Event batch emitter: sends events to POST /events/ingest using httpx + ThreadPoolExecutor.

IMPROVEMENT: Switched from blocking `requests` to non-blocking `httpx` with a
background ThreadPoolExecutor. This prevents each camera's detection loop from
stalling while waiting for HTTP responses — all 5 cameras can now emit concurrently
without blocking each other.

Optionally publishes to Redis Streams instead of HTTP when REDIS_URL is set.
Fall back to direct HTTP if Redis is unavailable.
"""
import os
import time
import concurrent.futures
import structlog
import httpx
from typing import Optional

log = structlog.get_logger()

API_URL = os.environ.get("API_URL", "http://localhost:8000")
BATCH_SIZE = int(os.environ.get("EMIT_BATCH_SIZE", 100))
REDIS_URL = os.environ.get("REDIS_URL", "")       # e.g. redis://localhost:6379
REDIS_STREAM = os.environ.get("REDIS_STREAM", "store:events")
RETRY_ATTEMPTS = 3


def _try_get_redis():
    """Return a Redis client if REDIS_URL is set and Redis is reachable, else None."""
    if not REDIS_URL:
        return None
    try:
        import redis as redis_lib
        r = redis_lib.from_url(REDIS_URL, socket_connect_timeout=2, decode_responses=True)
        r.ping()
        log.info("emitter.redis_connected", url=REDIS_URL, stream=REDIS_STREAM)
        return r
    except Exception as exc:
        log.warning("emitter.redis_unavailable", error=str(exc), fallback="http")
        return None


class EventEmitter:
    """
    Buffers events and sends them in batches.

    Transport priority:
      1. Redis Streams  (if REDIS_URL is set and Redis is reachable)
      2. HTTP POST      (always available as fallback)

    HTTP calls run in a background ThreadPoolExecutor so the detection loop
    never blocks waiting for network I/O.
    """

    def __init__(self, batch_size: int = BATCH_SIZE):
        self._buffer: list[dict] = []
        self._batch_size = batch_size
        self._total_emitted = 0
        self._total_errors = 0
        # Thread pool for non-blocking HTTP sends (max 4 workers for 5 cameras)
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="emitter"
        )
        self._futures: list[concurrent.futures.Future] = []
        # Try Redis once on startup
        self._redis = _try_get_redis()

    def add(self, event: dict):
        """Add an event to the buffer. Flushes if batch size reached."""
        self._buffer.append(event)
        if len(self._buffer) >= self._batch_size:
            self.flush()

    def add_many(self, events: list[dict]):
        for e in events:
            self.add(e)

    def flush(self):
        """Send all buffered events — non-blocking via thread pool."""
        if not self._buffer:
            return

        batch = self._buffer[:]
        self._buffer.clear()

        if self._redis:
            # Fast path: publish directly to Redis Streams
            future = self._executor.submit(self._send_to_redis, batch)
        else:
            # Standard path: HTTP POST with retries
            future = self._executor.submit(self._send_via_http, batch)

        self._futures.append(future)

        # Prune completed futures to avoid memory leak
        self._futures = [f for f in self._futures if not f.done()]

    def drain(self):
        """Wait for all in-flight sends to complete. Call at pipeline end."""
        self.flush()  # Final flush of any remaining buffer
        for f in self._futures:
            try:
                f.result(timeout=30)
            except Exception as exc:
                log.error("emitter.drain_error", error=str(exc))
        self._futures.clear()
        self._executor.shutdown(wait=True)

    # ── Transport: Redis Streams ─────────────────────────────────────────────

    def _send_to_redis(self, batch: list[dict]):
        """Publish events to a Redis Stream. Each event is a separate message."""
        import json
        try:
            pipe = self._redis.pipeline(transaction=False)
            for event in batch:
                pipe.xadd(
                    REDIS_STREAM,
                    {"data": json.dumps(event)},
                    maxlen=100_000,   # Cap stream at 100k messages (circular buffer)
                    approximate=True,
                )
            pipe.execute()
            self._total_emitted += len(batch)
            log.info(
                "emitter.redis_sent",
                batch_size=len(batch),
                stream=REDIS_STREAM,
            )
        except Exception as exc:
            log.warning("emitter.redis_error", error=str(exc), fallback="http")
            # Redis failed mid-session — degrade to HTTP for this batch
            self._send_via_http(batch)

    # ── Transport: HTTP POST (httpx, non-blocking from caller's perspective) ─

    def _send_via_http(self, batch: list[dict]):
        """POST events to /events/ingest with exponential-backoff retries."""
        for attempt in range(RETRY_ATTEMPTS):
            try:
                with httpx.Client(timeout=30) as client:
                    resp = client.post(
                        f"{API_URL}/events/ingest",
                        json={"events": batch},
                    )
                resp.raise_for_status()
                result = resp.json()
                self._total_emitted += result.get("accepted", 0)
                log.info(
                    "emitter.batch_sent",
                    accepted=result.get("accepted"),
                    duplicates=result.get("duplicates"),
                    errors=result.get("errors"),
                    batch_size=len(batch),
                    transport="http",
                )
                return
            except Exception as exc:
                log.warning("emitter.retry", attempt=attempt + 1, error=str(exc))
                time.sleep(2 ** attempt)

        self._total_errors += len(batch)
        log.error("emitter.batch_failed", batch_size=len(batch))

    @property
    def stats(self) -> dict:
        return {
            "total_emitted": self._total_emitted,
            "total_errors": self._total_errors,
            "transport": "redis" if self._redis else "http",
        }
