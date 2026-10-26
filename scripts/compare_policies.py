"""Policy comparison on identical simulated environments (same seed => same weather, demand, incidents).

All policies except `none` receive the same budget: 12 units per 30 days, accumulating (patch = 1, resurface = 12).

  none    : no maintenance
  fixed   : calendar rotation, resurfacing one segment whenever the budget allows (about every 30 days)
  inspect : ORACLE periodic inspection every 30 days: sees the true condition and every pothole for free,
            then spends the budget with the same priority rule as the twin (an optimistic baseline)
  twin30  : the twin's estimates, deciding every 30 days (same cadence as the inspection baseline)
  twin7   : the twin's estimates, deciding every 7 days (continuous monitoring allows faster response)

All results are SIMULATION outcomes under stated model assumptions, not field evidence.
"""
import argparse
import csv
import statistics
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from routetwin.contracts import MaintenanceEvent  # noqa: E402
from routetwin.corridor import load_corridor  # noqa: E402
from routetwin.decision import COST, maintenance_queue  # noqa: E402
from routetwin.simulator import SimConfig, World  # noqa: E402
from routetwin.twin import TwinEngine  # noqa: E402

TICKS_PER_DAY = 144
PERIOD_DAYS = 30
BUDGET = 12.0
POLICIES = ("none", "fixed", "inspect", "twin30", "twin7")


def truth_queue(w, cor):
    segs = [{"id": i, "name": cor.segments[i].name, "ci": float(c), "rul_days": None,
             "potholes": [0] * len(w.potholes[i])} for i, c in enumerate(w.ci_true())]
    return maintenance_queue(segs)


def run(args):
    policy, seed, days = args
    cor = load_corridor()
    w = World(cor, SimConfig(seed=seed, demo_script=False))
    uses_twin = policy in ("twin30", "twin7")
    eng = TwinEngine(cor) if uses_twin else None
    period = 7 if policy == "twin7" else PERIOD_DAYS
    daily_ci, below, pot_days, spend, errs = [], 0, 0, 0.0, []
    budget, rot = 0.0, 0
    for k in range(1, days * TICKS_PER_DAY + 1):
        msgs = w.step(emit=uses_twin, emit_positions=False)
        if eng:
            eng.ingest(msgs)
            eng.evaluate(w.ts)
        if k % TICKS_PER_DAY == 0:
            day = k // TICKS_PER_DAY
            ci = w.ci_true()
            daily_ci.append(float(ci.mean()))
            below += int((ci < 45).sum())
            pot_days += sum(len(p) for p in w.potholes)
            if policy != "none":
                budget += BUDGET / PERIOD_DAYS
            if eng and day % 5 == 0:
                snap = eng.snapshot()
                errs.append(float(np.mean([abs(s["ci"] - t) for s, t in zip(snap["segments"], ci)])))
            if policy != "none" and day % period == 0:
                if policy == "fixed":
                    if budget >= COST["resurface"]:
                        w.apply_maintenance(rot % cor.n, "resurface")
                        rot += 1
                        budget -= COST["resurface"]
                        spend += COST["resurface"]
                else:
                    queue = eng.snapshot()["maintenance"] if eng else truth_queue(w, cor)
                    for item in queue:
                        c = item["cost"]
                        if item["action"] != "monitor" and c <= budget:
                            w.apply_maintenance(item["segment_id"], item["action"])
                            if eng:
                                eng.ingest([MaintenanceEvent(ts=w.ts, source="policy", segment_id=item["segment_id"],
                                                             action=item["action"])])
                            budget -= c
                            spend += c
    return {"policy": policy, "seed": seed, "days": days, "mean_ci": statistics.mean(daily_ci),
            "min_ci_end": float(w.ci_true().min()), "segment_days_below_45": below,
            "pothole_days": pot_days, "spend_units": spend,
            "twin_ci_mae": statistics.mean(errs) if errs else float("nan")}


def summarize(rows, days, seeds):
    print(f"{days} simulated days, {seeds} seeds (mean over seeds)")
    print(f"{'policy':9}{'mean CI':>9}{'seg-days CI<45':>16}{'pothole-days':>14}{'spend':>8}{'twin CI MAE':>13}")
    for p in POLICIES:
        r = [x for x in rows if x["policy"] == p]
        if not r:
            continue
        m = lambda key: statistics.mean(float(x[key]) for x in r)
        print(f"{p:9}{m('mean_ci'):9.2f}{m('segment_days_below_45'):16.0f}{m('pothole_days'):14.0f}{m('spend_units'):8.0f}"
              f"{m('twin_ci_mae'):13.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--fresh", action="store_true", help="discard previous partial results")
    a = ap.parse_args()
    out = Path(__file__).resolve().parent.parent / "data" / "simulated" / "policy_comparison.csv"
    rows = []
    if out.exists() and not a.fresh:
        rows = [r for r in csv.DictReader(out.open()) if int(r["days"]) == a.days]
    done = {(r["policy"], int(r["seed"])) for r in rows}
    fields = ["policy", "seed", "days", "mean_ci", "min_ci_end", "segment_days_below_45", "pothole_days",
              "spend_units", "twin_ci_mae"]
    if a.fresh or not out.exists() or not rows:
        with out.open("w", newline="") as f:
            csv.DictWriter(f, fieldnames=fields).writeheader()
        rows, done = [], set()
    for seed in range(1, a.seeds + 1):
        for p in POLICIES:
            if (p, seed) in done:
                continue
            r = run((p, seed, a.days))
            rows.append({k: str(v) for k, v in r.items()})
            with out.open("a", newline="") as f:
                csv.DictWriter(f, fieldnames=fields).writerow(r)
            print(f"finished {p} seed {seed}", flush=True)
    summarize(rows, a.days, a.seeds)
    print(f"raw rows: {out}")


if __name__ == "__main__":
    main()
