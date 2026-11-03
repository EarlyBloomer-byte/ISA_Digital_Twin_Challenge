"""Reproduces the headline figures quoted in the proposal for the 30-day demonstration run (seed 42, scripted storyline)."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from routetwin.corridor import load_corridor  # noqa: E402
from routetwin.simulator import SimConfig, World  # noqa: E402
from routetwin.twin import TwinEngine  # noqa: E402

cor = load_corridor()
w, e = World(cor, SimConfig(seed=42, demo_script=True)), TwinEngine(cor)
for _ in range(144 * 30):
    e.ingest(w.step(emit_positions=False)); e.evaluate(w.ts)
s, t = e.snapshot(), w.snapshot_truth()
err = [abs(x["ci"] - c) for x, c in zip(s["segments"], t["ci"])]
print(f"CI mean absolute error after 30 days: {np.mean(err):.2f} points (max {max(err):.2f})")
print("potholes estimated:", [len(x["potholes"]) for x in s["segments"]])
print("potholes true     :", [len(p) for p in t["potholes"]])
