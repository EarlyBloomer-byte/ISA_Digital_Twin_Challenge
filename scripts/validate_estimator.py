"""Estimator validation in simulation: filter consistency and model mismatch.

matched    : the simulated truth follows the same model family as the twin (what the main results use)
mismatched : the truth uses a different load exponent (3.2 instead of 4) and a different IRI(D) curve
             (beta 1.6, span 6 instead of 1.3 and 7), and the twin is NOT told. An overloading surge is
             injected on day 20 in both cases.

Reported: mean absolute condition-index (CI) error after a 10-day burn-in, the share of segment-days where the
true CI lies within two reported standard deviations, and the mean normalised innovation squared (NIS) of the
filters (about 1 when the filter is consistent). All results are SIMULATION results.
"""
import argparse, csv, statistics, sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from routetwin import pavement as pv  # noqa: E402
from routetwin.corridor import load_corridor  # noqa: E402
from routetwin.simulator import SimConfig, World  # noqa: E402
from routetwin.twin import TwinEngine  # noqa: E402

CASES = {"matched": {}, "mismatched": {"damage_exponent": 3.2, "iri_beta": 1.6, "iri_span": 6.0}}


def run(case, seed, days):
    cor = load_corridor()
    w = World(cor, SimConfig(seed=seed, demo_script=False, **CASES[case]))
    e = TwinEngine(cor)
    errs, inside, total, bias = [], 0, 0, []
    for k in range(1, days * 144 + 1):
        if k == 20 * 144:
            w.trigger("overload", mult=1.35, days=10)
        e.ingest(w.step(emit_positions=False))
        e.evaluate(w.ts)
        if k % 144 == 0 and k > 10 * 144:
            snap, truth = e.snapshot(), w.ci_true()
            for s, t in zip(snap["segments"], truth):
                d = s["ci"] - float(t)
                errs.append(abs(d)); bias.append(d)
                inside += abs(d) <= 2 * max(s["ci_sd"], 1e-6); total += 1
    nis = [s.ekf.nis_sum / s.ekf.nis_n for s in e.segs if s.ekf.nis_n]
    return {"case": case, "seed": seed, "days": days, "ci_mae": statistics.mean(errs), "ci_bias": statistics.mean(bias),
            "coverage_2sd": inside / total, "mean_nis": statistics.mean(nis)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--seeds", type=int, default=3)
    a = ap.parse_args()
    out = Path(__file__).resolve().parent.parent / "data" / "simulated" / "estimator_validation.csv"
    rows = []
    for case in CASES:
        for seed in range(1, a.seeds + 1):
            rows.append(run(case, seed, a.days)); print("finished", case, seed, flush=True)
    with out.open("w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0])); wr.writeheader(); wr.writerows(rows)
    lines = [f"# Estimator validation ({a.days} simulated days, {a.seeds} seeds, mean over seeds; simulation only)", "",
             "| Case | CI MAE (points) | CI bias (points) | Truth within 2 SD | Mean NIS |", "|---|---:|---:|---:|---:|"]
    for case in CASES:
        r = [x for x in rows if x["case"] == case]; m = lambda k: statistics.mean(x[k] for x in r)
        lines.append(f"| {case} | {m('ci_mae'):.2f} | {m('ci_bias'):+.2f} | {100 * m('coverage_2sd'):.0f}% | {m('mean_nis'):.2f} |")
    lines += ["", "NIS near 1 means the filter's stated uncertainty matches its actual innovations; well above 1 means it is overconfident.",
              "Mismatched truth: load exponent 3.2 (twin assumes 4), IRI(D) with beta 1.6 and span 6 (twin assumes 1.3 and 7)."]
    (Path(__file__).resolve().parent.parent / "docs" / "validation.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
