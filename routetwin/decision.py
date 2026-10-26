"""Decision support: dispatcher advisories and maintenance prioritisation."""
from __future__ import annotations

from .corridor import Corridor

COST = {"patch": 1.0, "resurface": 12.0}
ADVISORY_MIN_DELAY_H = 0.25
LOOKAHEAD_KM = 80.0
SLOW_KMH = 30.0


def maintenance_queue(segments: list[dict]) -> list[dict]:
    out = []
    for s in segments:
        ci, rul = s["ci"], s["rul_days"]
        n_pot = len(s["potholes"])
        if ci < 45 or (rul is not None and rul < 45):
            action = "resurface"
        elif n_pot > 0:
            action = "patch"
        else:
            action = "monitor"
        score = (0.5 * (1 - ci / 100.0) + 0.3 * min(1.0, n_pot / 3.0)
                 + 0.2 * (0.0 if rul is None else max(0.0, 1.0 - rul / 180.0)))
        out.append({"segment_id": s["id"], "name": s["name"], "action": action, "priority": round(score, 3),
                    "ci": ci, "rul_days": rul, "potholes": n_pot, "cost": COST.get(action, 0.0)})
    return sorted(out, key=lambda r: -r["priority"])


def traffic_advisories(cor: Corridor, segments: list[dict], closed: set[int]) -> list[dict]:
    """Segment-level reroute / hold advice for heavy vehicles approaching a slow or closed segment.

    The twin models the road, so advice is addressed to the road's users in general
    (dispatchers of incoming trucks), not to individual vehicles.
    """
    out = []
    for s in segments:
        cs = cor.segments[s["id"]]
        blocked = s["id"] in closed
        worst = None  # (extra_h, direction, speed)
        for d in (0, 1):
            sp = s["speed"][d]
            if sp is None and not blocked:
                continue
            sp_eff = 2.0 if blocked else max(sp, 2.0)
            if sp_eff < SLOW_KMH:
                extra = cs.length_km / sp_eff - cs.length_km / cs.free_flow_kmh
                if worst is None or extra > worst[0]:
                    worst = (extra, d, sp_eff)
        if worst is None or worst[0] < 0.1:
            continue
        extra, d, sp_eff = worst
        way = "Lagos to Ibadan" if d == 0 else "Ibadan to Lagos"
        label = "closed" if blocked else f"{sp_eff:.0f} km/h"
        kind, text = "hold", ""
        if cs.bypass:
            b_h = (cs.length_km + cs.bypass["extra_km"]) / cs.bypass["speed_kmh"] - cs.length_km / cs.free_flow_kmh
            if b_h < extra:
                kind = "bypass"
                text = (f"{s['name']} ({way}) is {label}: about {extra * 60:.0f} min extra through the segment. "
                        f"Reroute incoming heavy vehicles via the bypass (+{cs.bypass['extra_km']:.0f} km), "
                        f"saving about {(extra - b_h) * 60:.0f} min.")
        if kind == "hold":
            text = (f"{s['name']} ({way}) is {label}: about {extra * 60:.0f} min extra through the segment and no "
                    f"bypass is defined. Hold or reschedule incoming heavy vehicles upstream.")
        out.append({"segment_id": s["id"], "direction": d, "kind": kind, "delay_min": round(extra * 60, 1), "text": text})
    return sorted(out, key=lambda a: -a["delay_min"])
