"""
Redis Streams consumer — reads events from a Redis Stream and forwards
them to the FastAPI ingest endpoint in batches.

Run this as a standalone process alongside your detection pipeline:
    python -m pipeline.redis_consumer

Environment variables:
    REDIS_URL      e.g. redis://localhost:6379 (default: redis://localhost:6379)
    REDIS_STREAM   stream name (default: store:events)
    REDIS_GROUP    consumer group (default: ingest_workers)
    API_URL        FastAPI ingest URL (default: http://localhost:8000)
    CONSUMER_BATCH max events per ingest call (default: 50)
    POLL_TIMEOUT   ms to block on XREADGROUP (default: 1000)
"""
import os
import json
import time
import signal
import sys
import httpx
import structlog

log = structlog.get_logger()

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
REDIS_STREAM = os.environ.get("REDIS_STREAM", "store:events")
REDIS_GROUP = os.environ.get("REDIS_GROUP", "ingest_workers")
CONSUMER_NAME = os.environ.get("CONSUMER_NAME", "consumer-1")
API_URL = os.environ.get("API_URL", "http://localhost:8000")
CONSUMER_BATCH = int(os.environ.get("CONSUMER_BATCH", 50))
POLL_TIMEOUT_MS = int(os.environ.get("POLL_TIMEOUT", 1000))

_running = True


def _handle_sigterm(sig, frame):
    global _running
    log.info("consumer.shutdown_signal")
    _running = False


def _ensure_group(r):
    """Create the consumer group if it doesn't exist."""
    try:
        r.xgroup_create(REDIS_STREAM, REDIS_GROUP, id="0", mkstream=True)
        log.info("consumer.group_created", group=REDIS_GROUP, stream=REDIS_STREAM)
    except Exception as exc:
        if "BUSYGROUP" in str(exc):
            log.info("consumer.group_exists", group=REDIS_GROUP)
        else:
            raise


def _post_to_api(events: list[dict]) -> int:
    """POST events to /events/ingest. Returns number accepted."""
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(f"{API_URL}/events/ingest", json={"events": events})
            resp.raise_for_status()
            result = resp.json()
            return result.get("accepted", 0)
    except Exception as exc:
        log.error("consumer.api_error", error=str(exc), batch_size=len(events))
        return 0


def run():
    """Main consumer loop: XREADGROUP → batch → POST → ACK."""
    import redis as redis_lib

    r = redis_lib.from_url(REDIS_URL, decode_responses=True)
    _ensure_group(r)

    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)

    log.info(
        "consumer.started",
        stream=REDIS_STREAM,
        group=REDIS_GROUP,
        consumer=CONSUMER_NAME,
        api=API_URL,
    )

    total_consumed = 0
    total_accepted = 0

    while _running:
        try:
            # Read up to CONSUMER_BATCH messages, block for POLL_TIMEOUT_MS
            messages = r.xreadgroup(
                groupname=REDIS_GROUP,
                consumername=CONSUMER_NAME,
                streams={REDIS_STREAM: ">"},
                count=CONSUMER_BATCH,
                block=POLL_TIMEOUT_MS,
            )

            if not messages:
                continue

            ids_to_ack = []
            events_batch = []

            for stream_name, stream_msgs in messages:
                for msg_id, fields in stream_msgs:
                    try:
                        event = json.loads(fields["data"])
                        events_batch.append(event)
                        ids_to_ack.append(msg_id)
                    except Exception as exc:
                        log.warning("consumer.parse_error", msg_id=msg_id, error=str(exc))
                        ids_to_ack.append(msg_id)  # ACK bad messages to avoid re-delivery

            if events_batch:
                accepted = _post_to_api(events_batch)
                total_consumed += len(events_batch)
                total_accepted += accepted
                log.info(
                    "consumer.batch_processed",
                    batch_size=len(events_batch),
                    accepted=accepted,
                    total_consumed=total_consumed,
                    total_accepted=total_accepted,
                )

            # ACK all messages so they are removed from the pending list
            if ids_to_ack:
                r.xack(REDIS_STREAM, REDIS_GROUP, *ids_to_ack)

        except Exception as exc:
            log.error("consumer.loop_error", error=str(exc))
            time.sleep(2)

    log.info("consumer.stopped", total_consumed=total_consumed, total_accepted=total_accepted)


if __name__ == "__main__":
    import structlog
    structlog.configure(
        processors=[structlog.dev.ConsoleRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(20),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )
    run()
