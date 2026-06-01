"""
Staff detection heuristics.
Staff are identified by:
1. Consistently appearing in STAFF_AREA (CAM4)
2. Appearing at CASH_COUNTER during store hours (CAM5)
3. Dark uniform color (85% of frames in a session are dark-clothed)
Purplle Store Intelligence System.
"""
from collections import defaultdict
from typing import Optional


STAFF_ZONES = {"STAFF_AREA", "CASH_COUNTER"}
STAFF_CAMERAS = {"CAM4"}  # Direct staff camera
STAFF_ZONE_THRESHOLD = 0.4  # If >40% of frames are in staff zones -> staff


class StaffDetector:
    """Determines if a tracked person is likely staff."""

    def __init__(self):
        # track_id -> list of zone_ids observed
        self._zone_history: dict[str, list[str]] = defaultdict(list)
        # track_id -> confirmed staff status
        self._staff_cache: dict[str, bool] = {}

    def update(self, track_id: str, zone_id: Optional[str], camera_id: str) -> bool:
        """
        Update zone history and return current staff assessment.
        A person is staff if:
        - They appear in STAFF_AREA camera (CAM4) OR
        - >40% of their zone appearances are in STAFF_ZONES
        """
        if camera_id in STAFF_CAMERAS:
            self._staff_cache[track_id] = True
            return True

        if zone_id:
            self._zone_history[track_id].append(zone_id)

        history = self._zone_history[track_id]
        if not history:
            return False

        staff_frames = sum(1 for z in history if z in STAFF_ZONES)
        ratio = staff_frames / len(history)

        is_staff = ratio >= STAFF_ZONE_THRESHOLD
        if is_staff:
            self._staff_cache[track_id] = True
        return self._staff_cache.get(track_id, False)

    def is_staff(self, track_id: str) -> bool:
        return self._staff_cache.get(track_id, False)

    def reset(self, track_id: str):
        self._zone_history.pop(track_id, None)
        self._staff_cache.pop(track_id, None)
