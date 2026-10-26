import numpy as np

from routetwin.corridor import haversine_km, load_corridor
from routetwin.geometry_osm import centerline_from_nodes, resample_polyline


def test_corridor_loads_and_chainage_is_continuous():
    c = load_corridor()
    assert c.n == 13 and 100 < c.length_km < 130
    for a, b in zip(c.segments, c.segments[1:]):
        assert abs(a.chainage_start_km + a.length_km - b.chainage_start_km) < 1e-9
        assert a.end == b.start


def test_locate_and_project_roundtrip():
    c = load_corridor()
    lat, lon, sid, off = c.locate_chainage(57.3)
    ch, sid2 = c.project(lat, lon)
    assert sid == sid2 and abs(ch - 57.3) < 0.05


def test_osm_centerline_collapses_dual_carriageway():
    a, b = (6.6, 3.4), (7.0, 3.8)
    rng = np.random.default_rng(1)
    nodes = []
    for t in np.linspace(0, 1, 400):
        for off in (-0.0008, 0.0008):  # two carriageways about 180 m apart
            nodes.append((a[0] + t * (b[0] - a[0]) + off + rng.normal(0, 1e-5), a[1] + t * (b[1] - a[1]) - off))
    centre = centerline_from_nodes(nodes, a, b, bin_km=2.0)
    pts = resample_polyline(centre, 10)
    assert len(pts) == 11
    seg = [haversine_km(*p, *q) for p, q in zip(pts, pts[1:])]
    assert max(seg) / min(seg) < 1.15  # equal-length segments
