"""
Session lifecycle tracker: ENTRY, EXIT, REENTRY, ZONE_ENTER/EXIT, DWELL.
Purplle Store Intelligence System.
"""
import uuid
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional

from pipeline.zones import Zone


@dataclass
class PersonSession:
    session_id: str
    person_id: str
    track_id: int
    camera_id: str
    store_id: str
    entry_time: datetime
    is_staff: bool = False
    current_zone: Optional[str] = None
    zone_entry_time: Optional[datetime] = None
    zones_visited: list[str] = field(default_factory=list)
    last_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    exited: bool = False


class SessionTracker:
    """Tracks person sessions across frames within a camera."""

    # After this many seconds unseen, emit EXIT
    EXIT_TIMEOUT_S = 10
    # Minimum dwell before emitting DWELL event
    MIN_DWELL_S = 5

    def __init__(self, camera_id: str, store_id: str):
        self.camera_id = camera_id
        self.store_id = store_id
        # track_id -> PersonSession
        self._sessions: dict[int, PersonSession] = {}
        # track_id -> person_id (for re-entry)
        self._track_to_person: dict[int, str] = {}
        self._events: list[dict] = []

    def update(
        self,
        track_id: int,
        zone: Optional[Zone],
        is_staff: bool,
        timestamp: datetime,
    ) -> list[dict]:
        """Process a single detection frame for a track ID. Returns new events."""
        emitted = []

        if track_id not in self._sessions:
            # New track: ENTRY
            person_id = self._track_to_person.get(track_id, f"{self.camera_id}_{track_id}_{uuid.uuid4().hex[:6]}")
            self._track_to_person[track_id] = person_id
            session = PersonSession(
                session_id=str(uuid.uuid4()),
                person_id=person_id,
                track_id=track_id,
                camera_id=self.camera_id,
                store_id=self.store_id,
                entry_time=timestamp,
                is_staff=is_staff,
                last_seen=timestamp,
            )
            self._sessions[track_id] = session
            emitted.append(self._make_event("ENTRY", session, timestamp))
        else:
            session = self._sessions[track_id]
            session.last_seen = timestamp
            session.is_staff = is_staff

        # Zone transition
        zone_id = zone.zone_id if zone else None
        if zone_id != session.current_zone:
            if session.current_zone and session.zone_entry_time:
                # Emit ZONE_EXIT + DWELL for previous zone
                dwell = (timestamp - session.zone_entry_time).total_seconds()
                if dwell >= self.MIN_DWELL_S:
                    emitted.append(self._make_event(
                        "ZONE_EXIT", session, timestamp,
                        zone_id=session.current_zone,
                        dwell_seconds=dwell,
                    ))
                    if dwell >= self.MIN_DWELL_S:
                        emitted.append(self._make_event(
                            "ZONE_DWELL", session, timestamp,
                            zone_id=session.current_zone,
                            dwell_seconds=dwell,
                        ))

            if zone_id:
                # ZONE_ENTER new zone
                emitted.append(self._make_event("ZONE_ENTER", session, timestamp, zone_id=zone_id))
                if zone_id not in session.zones_visited:
                    session.zones_visited.append(zone_id)

            session.current_zone = zone_id
            session.zone_entry_time = timestamp if zone_id else None

        return emitted

    def flush_stale(self, current_time: datetime) -> list[dict]:
        """Emit EXIT for tracks not seen recently."""
        emitted = []
        stale = [
            tid for tid, sess in self._sessions.items()
            if not sess.exited and
               (current_time - sess.last_seen).total_seconds() > self.EXIT_TIMEOUT_S
        ]
        for tid in stale:
            sess = self._sessions[tid]
            if sess.current_zone and sess.zone_entry_time:
                dwell = (current_time - sess.zone_entry_time).total_seconds()
                if dwell >= self.MIN_DWELL_S:
                    emitted.append(self._make_event(
                        "ZONE_DWELL", sess, current_time,
                        zone_id=sess.current_zone, dwell_seconds=dwell,
                    ))
            emitted.append(self._make_event("EXIT", sess, current_time))
            sess.exited = True
            del self._sessions[tid]
        return emitted

    def _make_event(self, event_type: str, session: PersonSession,
                    timestamp: datetime, zone_id: Optional[str] = None,
                    dwell_seconds: Optional[float] = None) -> dict:
        return {
            "event_id": str(uuid.uuid4()),
            "store_id": session.store_id,
            "camera_id": session.camera_id,
            "event_type": event_type,
            "person_id": session.person_id,
            "is_staff": session.is_staff,
            "zone_id": zone_id or session.current_zone,
            "timestamp": timestamp.isoformat(),
            "dwell_seconds": round(dwell_seconds, 2) if dwell_seconds is not None else None,
            "confidence": 0.9,
            "metadata": {"session_id": session.session_id, "track_id": session.track_id},
        }
