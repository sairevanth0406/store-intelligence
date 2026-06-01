"""
Zone polygon mapper using real Purplle Brigade Road store layout.
Maps camera-space bounding box centroids to named brand zones.
Purplle Store Intelligence System.
"""
import json
import os
from dataclasses import dataclass, field
from typing import Optional

try:
    from shapely.geometry import Point, Polygon
    SHAPELY_AVAILABLE = True
except ImportError:
    SHAPELY_AVAILABLE = False


@dataclass
class Zone:
    zone_id: str
    display_name: str
    category: str
    brand: Optional[str]
    polygon: list  # list of [x, y] points (camera space)
    camera_id: str
    color: str = "#888888"
    _poly: object = field(default=None, repr=False)  # Shapely polygon

    def __post_init__(self):
        if SHAPELY_AVAILABLE and self.polygon:
            self._poly = Polygon([(p[0], p[1]) for p in self.polygon])

    def contains_point(self, x: float, y: float) -> bool:
        """Check if point (x,y) is within this zone."""
        if SHAPELY_AVAILABLE and self._poly:
            return self._poly.contains(Point(x, y))
        # Fallback: bounding box test
        if not self.polygon:
            return False
        xs = [p[0] for p in self.polygon]
        ys = [p[1] for p in self.polygon]
        return min(xs) <= x <= max(xs) and min(ys) <= y <= max(ys)


class ZoneMapper:
    """Maps camera bounding boxes to named brand zones."""

    LAYOUT_PATH = os.path.join(
        os.path.dirname(__file__), "..", "data", "store_layout.json"
    )

    def __init__(self, camera_id: str):
        self.camera_id = camera_id
        self.zones: list[Zone] = []
        self._load_zones()

    def _load_zones(self):
        """Load zones from store_layout.json for this camera."""
        with open(self.LAYOUT_PATH) as f:
            layout = json.load(f)

        cam_key = f"polygon_{self.camera_id.lower()}"
        for zone_id, meta in layout.get("zones", {}).items():
            if cam_key not in meta:
                continue
            self.zones.append(Zone(
                zone_id=zone_id,
                display_name=meta.get("display_name", zone_id),
                category=meta.get("category", "unknown"),
                brand=meta.get("brand"),
                polygon=meta[cam_key],
                camera_id=self.camera_id,
                color=meta.get("color", "#888888"),
            ))

    def get_zone(self, bbox_x1: float, bbox_y1: float, bbox_x2: float, bbox_y2: float) -> Optional[Zone]:
        """Get the zone for a bounding box centroid."""
        cx = (bbox_x1 + bbox_x2) / 2
        cy = (bbox_y1 + bbox_y2) / 2  # Use full centroid for camera space
        # Use bottom-center of bbox (feet position) for floor zone mapping
        foot_x = cx
        foot_y = bbox_y2
        for zone in self.zones:
            if zone.contains_point(foot_x, foot_y):
                return zone
        return None

    def get_all_zones(self) -> list[Zone]:
        return self.zones
