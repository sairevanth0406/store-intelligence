"""
Event batch emitter: sends events to POST /events/ingest.
Purplle Store Intelligence System.
"""
import os
import time
import requests
import structlog
from typing import Optional

log = structlog.get_logger()

API_URL = os.environ.get("API_URL", "http://localhost:8000")
BATCH_SIZE = int(os.environ.get("EMIT_BATCH_SIZE", 100))
RETRY_ATTEMPTS = 3


class EventEmitter:
    """Buffers events and sends them in batches to the ingest API."""

    def __init__(self, batch_size: int = BATCH_SIZE):
        self._buffer: list[dict] = []
        self._batch_size = batch_size
        self._total_emitted = 0
        self._total_errors = 0

    def add(self, event: dict):
        """Add an event to the buffer. Flushes if batch size reached."""
        self._buffer.append(event)
        if len(self._buffer) >= self._batch_size:
            self.flush()

    def add_many(self, events: list[dict]):
        for e in events:
            self.add(e)

    def flush(self):
        """Send all buffered events to the API."""
        if not self._buffer:
            return

        batch = self._buffer[:]
        self._buffer.clear()

        for attempt in range(RETRY_ATTEMPTS):
            try:
                resp = requests.post(
                    f"{API_URL}/events/ingest",
                    json={"events": batch},
                    timeout=30,
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
                )
                return
            except Exception as exc:
                log.warning("emitter.retry", attempt=attempt + 1, error=str(exc))
                time.sleep(2 ** attempt)

        self._total_errors += len(batch)
        log.error("emitter.batch_failed", batch_size=len(batch))

    @property
    def stats(self) -> dict:
        return {"total_emitted": self._total_emitted, "total_errors": self._total_errors}
