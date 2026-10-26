"""Corridor geometry and static segment parameters."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

EARTH_R = 6371.0088  # km
DEFAULT_CORRIDOR = Path(__file__).resolve().parent.parent / "data" / "corridor_lagos_ibadan.json"


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


@dataclass
class Segment:
    id: int
    name: str
    start: tuple[float, float]
    end: tuple[float, float]
    length_km: float
    chainage_start_km: float
    lanes: int
    free_flow_kmh: float
    capacity_factor: float
    bypass: Optional[dict] = None


@dataclass
class Corridor:
    name: str
    geometry_status: str
    design_esal: float
    segments: list[Segment] = field(default_factory=list)
    waypoints: list[dict] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.segments)

    @property
    def length_km(self) -> float:
        return sum(s.length_km for s in self.segments)

    def locate(self, seg_id: int, offset_m: float) -> tuple[float, float]:
        """Lat/lon of a point `offset_m` metres into segment `seg_id` (outbound direction)."""
        s = self.segments[seg_id]
        f = min(max(offset_m / (s.length_km * 1000.0), 0.0), 1.0)
        return (s.start[0] + f * (s.end[0] - s.start[0]), s.start[1] + f * (s.end[1] - s.start[1]))

    def locate_chainage(self, chainage_km: float) -> tuple[float, float, int, float]:
        """Return (lat, lon, segment_id, offset_m) for a corridor chainage."""
        c = min(max(chainage_km, 0.0), self.length_km - 1e-9)
        for s in self.segments:
            if c < s.chainage_start_km + s.length_km:
                off = (c - s.chainage_start_km) * 1000.0
                lat, lon = self.locate(s.id, off)
                return lat, lon, s.id, off
        s = self.segments[-1]
        return s.end[0], s.end[1], s.id, s.length_km * 1000.0

    def project(self, lat: float, lon: float) -> tuple[float, int]:
        """Project a GPS fix onto the corridor: returns (chainage_km, segment_id)."""
        best = (1e18, 0.0, 0)
        for s in self.segments:
            k = math.cos(math.radians((s.start[0] + s.end[0]) / 2))
            ax, ay = s.start[1] * k, s.start[0]
            bx, by = s.end[1] * k, s.end[0]
            px, py = lon * k, lat
            dx, dy = bx - ax, by - ay
            den = dx * dx + dy * dy
            t = 0.0 if den == 0 else min(max(((px - ax) * dx + (py - ay) * dy) / den, 0.0), 1.0)
            qx, qy = ax + t * dx, ay + t * dy
            d2 = (px - qx) ** 2 + (py - qy) ** 2
            if d2 < best[0]:
                best = (d2, s.chainage_start_km + t * s.length_km, s.id)
        return best[1], best[2]


def load_corridor(path: Path | str | None = None) -> Corridor:
    p = Path(path) if path else DEFAULT_CORRIDOR
    raw = json.loads(p.read_text())
    wps = raw["waypoints"]
    if len(raw["segments"]) != len(wps) - 1:
        raise ValueError("segments must equal waypoints - 1")
    segs: list[Segment] = []
    ch = 0.0
    for i, sp in enumerate(raw["segments"]):
        a, b = wps[i], wps[i + 1]
        length = haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
        label = f"S{i + 1:02d}"
        names = [x.get("name") for x in (a, b) if x.get("name")]
        if names:
            label += " " + " / ".join(names)
        segs.append(Segment(
            id=i, name=label, start=(a["lat"], a["lon"]), end=(b["lat"], b["lon"]),
            length_km=length, chainage_start_km=ch, lanes=sp["lanes"],
            free_flow_kmh=sp["free_flow_kmh"], capacity_factor=sp["capacity_factor"],
            bypass=sp.get("bypass"),
        ))
        ch += length
    return Corridor(
        name=raw["name"], geometry_status=raw.get("geometry_status", ""),
        design_esal=float(raw["design_esal_millions"]) * 1e6, segments=segs, waypoints=wps,
    )
