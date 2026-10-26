"""Replace the approximate corridor waypoints with an OpenStreetMap-derived centreline.

Needs internet. NOTE: written against the public Overpass API but not exercised against the live
service in the development sandbox; inspect the output before using it. Segment parameters (lanes,
free-flow speed, capacity factor, bypass) are copied from the existing corridor file by index.
"""
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from routetwin.geometry_osm import centerline_from_nodes, resample_polyline  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "corridor_lagos_ibadan.json"
DST = ROOT / "data" / "corridor_lagos_ibadan_osm.json"
QUERY = """[out:json][timeout:90];
(way["highway"~"motorway|trunk"]["name"~"Lagos.?Ibadan",i](6.4,3.2,7.6,4.2););
out geom;"""


def main():
    raw = json.loads(SRC.read_text())
    wps = raw["waypoints"]
    a, b = (wps[0]["lat"], wps[0]["lon"]), (wps[-1]["lat"], wps[-1]["lon"])
    r = httpx.post("https://overpass-api.de/api/interpreter", data={"data": QUERY}, timeout=120)
    r.raise_for_status()
    nodes = [(p["lat"], p["lon"]) for el in r.json().get("elements", []) for p in el.get("geometry", [])]
    if len(nodes) < 50:
        sys.exit(f"Only {len(nodes)} nodes returned; the name filter probably did not match. Adjust QUERY.")
    centre = centerline_from_nodes(nodes, a, b, bin_km=1.0)
    pts = resample_polyline(centre, len(raw["segments"]))
    new_wps = []
    for i, (lat, lon) in enumerate(pts):
        w = {"lat": round(lat, 5), "lon": round(lon, 5)}
        if i < len(wps) and wps[i].get("name") and i in (0, len(pts) - 1):
            w["name"] = wps[i]["name"]
        new_wps.append(w)
    raw["waypoints"] = new_wps
    raw["geometry_status"] = f"OSM-derived centreline from {len(nodes)} way nodes (Overpass); segment names no longer match landmarks"
    DST.write_text(json.dumps(raw, indent=2))
    print(f"wrote {DST}. Run with: python -m routetwin --corridor {DST}")


if __name__ == "__main__":
    main()
