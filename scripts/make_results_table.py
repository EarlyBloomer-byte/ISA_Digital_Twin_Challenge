"""Turn data/simulated/policy_comparison.csv into docs/results.md and docs/proposal/policy_table.tex."""
import csv
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
rows = list(csv.DictReader((ROOT / "data" / "simulated" / "policy_comparison.csv").open()))
ORDER = ["none", "fixed", "inspect", "twin30", "twin7"]
LABEL = {"none": "None", "fixed": "Fixed rotation", "inspect": "Oracle inspection, 30 d",
         "twin30": "Twin, 30 d", "twin7": "Twin, 7 d"}
days, seeds = rows[0]["days"], len({r["seed"] for r in rows})


def mean(policy, key):
    v = [float(r[key]) for r in rows if r["policy"] == policy]
    return statistics.mean(v)


def spread(policy, key):
    v = [float(r[key]) for r in rows if r["policy"] == policy]
    return max(v) - min(v)


lines = ["\\begin{tabular}{lrrrr}", "\\toprule",
         "Policy & Mean CI & Segment-days CI$<$45 & Pothole-days & Spend (units)\\\\", "\\midrule"]
md = [f"# Simulated maintenance policy comparison ({days} days, {seeds} seeds, mean over seeds)", "",
      "| Policy | Mean CI | Segment-days CI<45 | Pothole-days | Spend (units) | CI range across seeds |",
      "|---|---:|---:|---:|---:|---:|"]
for p in ORDER:
    if not any(r["policy"] == p for r in rows):
        continue
    a = (mean(p, "mean_ci"), mean(p, "segment_days_below_45"), mean(p, "pothole_days"), mean(p, "spend_units"))
    lines.append(f"{LABEL[p]} & {a[0]:.1f} & {a[1]:.0f} & {a[2]:.0f} & {a[3]:.0f}\\\\")
    md.append(f"| {LABEL[p]} | {a[0]:.1f} | {a[1]:.0f} | {a[2]:.0f} | {a[3]:.0f} | {spread(p, 'mean_ci'):.1f} |")
lines += ["\\bottomrule", "\\end{tabular}"]
(ROOT / "docs" / "proposal" / "policy_table.tex").write_text("\n".join(lines) + "\n")
md += ["", "All policies except None get the same budget: 12 units per 30 days, accumulating (patch 1, resurface 12).",
       "Environment (weather, demand, incidents) is identical across policies for a given seed.", "",
       "**How to quote these results.** They are simulation outcomes under illustrative parameters. Oracle inspection",
       "knows the true state of the road for free every 30 days, so it is an optimistic baseline; the twin's expected",
       "advantage is faster response through continuous monitoring and no inspection cost, not better guessing.",
       "Variability across seeds has not been characterised beyond the range column. Field evidence: none."]
(ROOT / "docs" / "results.md").write_text("\n".join(md) + "\n")
print("\n".join(md))
