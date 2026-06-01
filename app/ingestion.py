"""
POST /events/ingest — idempotent batch event ingestion.
Purplle Store Intelligence System.
"""
import json
from fastapi import APIRouter, HTTPException
from app.database import get_db
from app.models import IngestRequest, IngestResponse, EventResult
import structlog

router = APIRouter()
log = structlog.get_logger()

MAX_BATCH = 500


@router.post("/ingest", response_model=IngestResponse)
async def ingest_events(payload: IngestRequest):
    """
    Ingest a batch of up to 500 events.
    Uses INSERT OR IGNORE for idempotency on event_id (PRIMARY KEY).
    Returns per-event status with partial-success support.
    """
    # PROMPT: Implement batch ingest with idempotency. Use INSERT OR IGNORE so
    # that duplicate event_ids silently skip without error.
    # CHANGES MADE: Added partial-success: collect errors per event instead of
    # failing the entire batch. Returns structured per-event results.

    if len(payload.events) > MAX_BATCH:
        raise HTTPException(status_code=422, detail=f"Batch too large. Max {MAX_BATCH} events per request.")

    results: list[EventResult] = []
    accepted = 0
    duplicates = 0
    errors = 0

    db = await get_db()
    try:
        for event in payload.events:
            try:
                cursor = await db.execute(
                    """
                    INSERT OR IGNORE INTO events
                        (event_id, store_id, camera_id, event_type, person_id,
                         is_staff, zone_id, timestamp, dwell_seconds, confidence, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.store_id,
                        event.camera_id,
                        event.event_type.value,
                        event.person_id,
                        int(event.is_staff),
                        event.zone_id,
                        event.timestamp.isoformat(),
                        event.dwell_seconds,
                        event.confidence,
                        json.dumps(event.metadata) if event.metadata else None,
                    ),
                )
                if cursor.rowcount == 0:
                    results.append(EventResult(event_id=event.event_id, status="duplicate"))
                    duplicates += 1
                else:
                    results.append(EventResult(event_id=event.event_id, status="ok"))
                    accepted += 1

                    # Keep sessions table in sync
                    await _update_session(db, event)

            except Exception as exc:
                results.append(EventResult(event_id=event.event_id, status="error", error=str(exc)))
                errors += 1
                log.warning("ingest.event_error", event_id=event.event_id, error=str(exc))

        await db.commit()
    finally:
        await db.close()

    log.info(
        "ingest.batch_complete",
        accepted=accepted,
        duplicates=duplicates,
        errors=errors,
        batch_size=len(payload.events),
    )
    return IngestResponse(accepted=accepted, duplicates=duplicates, errors=errors, results=results)



async def _update_session(db, event):
    """Maintain sessions table from event stream."""
    from app.models import EventType
    import uuid

    if event.event_type == EventType.ENTRY:
        session_id = str(uuid.uuid4())
        await db.execute(
            """
            INSERT OR IGNORE INTO sessions
                (session_id, store_id, person_id, camera_id, entry_time, is_staff, zones_visited)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, event.store_id, event.person_id, event.camera_id,
             event.timestamp.isoformat(), int(event.is_staff), json.dumps([])),
        )

    elif event.event_type == EventType.EXIT:
        await db.execute(
            """
            UPDATE sessions
            SET exit_time = ?
            WHERE store_id = ? AND person_id = ? AND exit_time IS NULL
            """,
            (event.timestamp.isoformat(), event.store_id, event.person_id),
        )

    elif event.event_type in (EventType.ZONE_ENTER, EventType.ZONE_EXIT, EventType.DWELL, EventType.ZONE_DWELL):
        if event.zone_id:
            # Append zone to zones_visited
            row = await db.execute_fetchall(
                "SELECT session_id, zones_visited FROM sessions WHERE store_id=? AND person_id=? AND exit_time IS NULL ORDER BY entry_time DESC LIMIT 1",
                (event.store_id, event.person_id),
            )
            if row:
                session_id, zones_json = row[0]["session_id"], row[0]["zones_visited"]
                zones = json.loads(zones_json or "[]")
                if event.zone_id not in zones:
                    zones.append(event.zone_id)
                total_dwell = (event.dwell_seconds or 0)
                await db.execute(
                    "UPDATE sessions SET zones_visited=?, total_dwell_s=total_dwell_s+? WHERE session_id=?",
                    (json.dumps(zones), total_dwell, session_id),
                )

    elif event.event_type == EventType.CHECKOUT:
        await db.execute(
            "UPDATE sessions SET converted=1 WHERE store_id=? AND person_id=? AND exit_time IS NULL",
            (event.store_id, event.person_id),
        )
