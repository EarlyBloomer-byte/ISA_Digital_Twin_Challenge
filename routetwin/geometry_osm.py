"""Build a corridor centreline from OpenStreetMap way nodes (pure functions; network code lives in scripts/)."""
from __future__ import annotations

import math
import statistics

from .corridor import haversine_km


def _project(a, b, p):
    """Fractional position of p along the axis a->b (planar approximation) and its distance in km."""
    k = math.cos(math.radians((a[0] + b[0]) / 2))
    ax, ay, bx, by, px, py = a[1] * k, a[0], b[1] * k, b[0], p[1] * k, p[0]
    dx, dy = bx - ax, by - ay
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    return t


def centerline_from_nodes(nodes: list[tuple[float, float]], a: tuple[float, float], b: tuple[float, float],
                          bin_km: float = 1.0) -> list[tuple[float, float]]:
    """Collapse dual carriageways and side roads into one centreline by median-binning along the a->b axis."""
    total = haversine_km(a[0], a[1], b[0], b[1])
    bins: dict[int, list[tuple[float, float]]] = {}
    for p in nodes:
        t = _project(a, b, p)
        if 0.0 <= t <= 1.0:
            bins.setdefault(int(t * total / bin_km), []).append(p)
    out = []
    for k in sorted(bins):
        pts = bins[k]
        out.append((statistics.median(p[0] for p in pts), statistics.median(p[1] for p in pts)))
    return out


def resample_polyline(points: list[tuple[float, float]], n_segments: int) -> list[tuple[float, float]]:
    """Return n_segments + 1 points equally spaced (by length) along a polyline."""
    cum = [0.0]
    for p, q in zip(points, points[1:]):
        cum.append(cum[-1] + haversine_km(p[0], p[1], q[0], q[1]))
    total = cum[-1]
    res = []
    for i in range(n_segments + 1):
        target = total * i / n_segments
        j = max(1, next((k for k in range(1, len(cum)) if cum[k] >= target), len(cum) - 1))
        span = cum[j] - cum[j - 1] or 1e-12
        f = (target - cum[j - 1]) / span
        p, q = points[j - 1], points[j]
        res.append((p[0] + f * (q[0] - p[0]), p[1] + f * (q[1] - p[1])))
    return res
