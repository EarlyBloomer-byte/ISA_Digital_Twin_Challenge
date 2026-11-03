"""Runtime: wires a data mode (simulation / hybrid / live) to the twin engine and manages simulation runs."""
from __future__ import annotations

import secrets
import threading
import time
from pathlib import Path

from .contracts import MaintenanceEvent, Mode
from .corridor import load_corridor
from .security import AuditLog, IngestVerifier
from .simulator import MAX_SCENARIOS, SCENARIO_LABELS, SEGMENT_KINDS, SimConfig, World
from .twin import TwinConfig, TwinEngine
from .weather import SeriesWeather

DEFAULT_WEATHER = Path(__file__).resolve().parent.parent / "data" / "field" / "weather_lagos_ibadan.json"
CATALOG = [
    {"kind": "rain", "label": "Heavy rain", "detail": "72 h at 8 mm/h"},
    {"kind": "overload", "label": "Overloaded trucks", "detail": "7 days, gross weight +35%"},
    {"kind": "surge", "label": "Traffic surge", "detail": "3 days, demand +30%"},
    {"kind": "closure", "label": "Road closure", "detail": "12 h, both directions", "segment": True},
    {"kind": "accident", "label": "Accident", "detail": "3 h, one direction", "segment": True},
    {"kind": "sensor_outage", "label": "Sensor outage", "detail": "15 h, one station", "segment": True},
]


class NoRun(ValueError):
    """Raised when an action needs a running simulation and none is running."""


class Runtime:
    def __init__(self, mode: str | Mode = "simulation", seed: int = 42, corridor_path=None, weather_file=None,
                 demo_script: bool = True, audit_path=None, ingest_key: str | None = None,
                 operator_token: str | None = None, speed: int = 6, autostart: bool = True):
        self.mode = Mode(mode)
        self.cor = load_corridor(corridor_path)
        self.operator_token = operator_token
        self.audit = AuditLog(audit_path)
        self.lock = threading.RLock()
        self.speed = speed
        self.paused = False
        self.world: World | None = None
        self.engine: TwinEngine | None = None
        self.seed: int | None = None
        self.verifier: IngestVerifier | None = None

        if self.mode != Mode.simulation and not operator_token:
            raise RuntimeError("hybrid/live modes require ROUTETWIN_OPERATOR_TOKEN (control endpoints must be authenticated)")
        if self.mode == Mode.live:
            if not ingest_key:
                raise RuntimeError("live mode requires ROUTETWIN_INGEST_KEY for signed telemetry ingestion")
            self.verifier = IngestVerifier(ingest_key)

        self._tcfg = TwinConfig(auto_archive_rtn_s=6 * 3600.0 if self.mode != Mode.live else None)
        self._weather = SeriesWeather.from_file(weather_file or DEFAULT_WEATHER) if self.mode == Mode.hybrid else None
        if self.mode == Mode.live:
            self.engine = TwinEngine(self.cor, self._tcfg, mode=self.mode.value)
        elif autostart:   # the seeded, reproducible run used by tests, studies and `--demo`
            self.world = World(self.cor, SimConfig(seed=seed, demo_script=demo_script and self.mode == Mode.simulation),
                               weather=self._weather)
            self.engine = TwinEngine(self.cor, self._tcfg, mode=self.mode.value)
            self.seed = seed

    # ---------------------------------------------------------------- run lifecycle
    @property
    def running(self) -> bool:
        return self.engine is not None

    def _need_run(self):
        if not self.running:
            raise NoRun("No simulation is running")

    def start_run(self, seed: int | None = None, scenarios=()) -> int:
        """Start a fresh randomised run (new random road, worn sections and potholes) with up to three scenarios."""
        if self.mode == Mode.live:
            raise ValueError("Runs are not available in live mode")
        scenarios = list(scenarios)
        if len(scenarios) > MAX_SCENARIOS:
            raise ValueError("A maximum of three scenarios can be active at once")
        sd = secrets.randbits(32) if seed is None else int(seed) & 0xFFFFFFFF
        world = World(self.cor, SimConfig(seed=sd, demo_script=False, initial_potholes=True, wear_range=(0.15, 0.75)),
                      weather=self._weather)
        for sc in scenarios:
            kw = {k: v for k, v in dict(sc).items() if k != "kind" and v is not None}
            world.add_scenario(sc["kind"], **kw)
        with self.lock:
            self.world, self.engine, self.seed, self.paused = world, TwinEngine(self.cor, self._tcfg, mode=self.mode.value), sd, False
        self.audit.write("run_start", seed=sd, scenarios=[s["kind"] for s in scenarios])
        return sd

    def stop_run(self):
        if self.mode == Mode.live:
            raise ValueError("Runs are not available in live mode")
        with self.lock:
            self.world = self.engine = self.seed = None
            self.paused = False
        self.audit.write("run_stop")

    # ---------------------------------------------------------------- stepping
    def advance(self, n: int = 1, budget_s: float | None = None) -> int:
        """Advance up to n ticks; stops early when the time budget is used up. Returns the ticks done."""
        if self.world is None:
            return 0
        t0, done = time.monotonic(), 0
        with self.lock:
            while done < n and self.world is not None:
                if budget_s is not None and time.monotonic() - t0 > budget_s:
                    break
                self.engine.ingest(self.world.step())
                self.engine.evaluate(self.world.ts)
                done += 1
        return done

    def evaluate_live(self):
        with self.lock:
            if self.engine is not None:
                self.engine.evaluate(time.time())

    # ---------------------------------------------------------------- operator actions
    def trigger(self, kind: str, **kw):
        """Low-level scenario trigger (no limits); used by tests and the scripted demonstration."""
        if self.world is None:
            raise NoRun("Scenarios exist only where a simulated world runs")
        if self.mode == Mode.hybrid and kind == "rain":
            raise ValueError("rain is driven by recorded weather in hybrid mode")
        with self.lock:
            self.world.trigger(kind, **kw)
        self.audit.write("scenario", kind=kind, **kw)

    def add_scenario(self, kind: str, **kw):
        """Operator scenario with defaults; at most three active, no repeats."""
        if self.world is None:
            raise NoRun("No simulation is running")
        with self.lock:
            self.world.add_scenario(kind, **kw)
        self.audit.write("scenario", kind=kind, **{k: v for k, v in kw.items() if v is not None})

    def work_order(self, segment_id: int, action: str):
        if not 0 <= segment_id < self.cor.n:
            raise ValueError("unknown segment")
        with self.lock:
            self._need_run()
            ts = self.world.ts if self.world else time.time()
            if self.world:
                self.world.apply_maintenance(segment_id, action)
            self.engine.ingest([MaintenanceEvent(ts=ts, source="dashboard_work_order", segment_id=segment_id, action=action)])
        self.audit.write("work_order", segment_id=segment_id, action=action)

    def ack(self, alarm_id: int) -> bool:
        with self.lock:
            ok = self.engine is not None and self.engine.alarms.acknowledge(alarm_id, self.engine.ts)
        self.audit.write("ack", alarm_id=alarm_id, ok=ok)
        return ok

    def ack_all(self) -> int:
        with self.lock:
            n = self.engine.alarms.acknowledge_all(self.engine.ts) if self.engine is not None else 0
        self.audit.write("ack_all", count=n)
        return n

    # ---------------------------------------------------------------- views
    def snapshot(self, include_truth: bool = False) -> dict:
        with self.lock:
            if self.engine is None:
                return {"stopped": True, "control": {"speed": self.speed, "paused": False}}
            s = self.engine.snapshot()
            s["control"] = {"speed": self.speed, "paused": self.paused}
            s["clock"] = {"day": s["ts"] / 86400.0, "hour": (s["ts"] % 86400.0) / 3600.0}
            if self.world is not None:
                s["run"] = {"seed": self.seed, "max": MAX_SCENARIOS, "scenarios": self.world.scenario_status()}
                if include_truth:
                    s["truth"] = self.world.snapshot_truth()
            return s

    def history(self, segment_id: int) -> dict:
        with self.lock:
            self._need_run()
            twin = [{"ts": t, "ci": c, "sd": sd} for t, c, sd in self.engine.segs[segment_id].ci_history]
            truth = []
            if self.world is not None:
                truth = [{"ts": row[0], "ci": row[1 + segment_id]} for row in self.world.truth_history]
            return {"segment_id": segment_id, "twin": twin, "truth": truth}

    def config(self) -> dict:
        c = self.cor
        return {
            "mode": self.mode.value, "name": c.name, "geometry_status": c.geometry_status,
            "design_esal": c.design_esal, "length_km": c.length_km,
            "segments": [{"id": s.id, "name": s.name, "start": s.start, "end": s.end, "length_km": s.length_km,
                          "chainage_start_km": s.chainage_start_km, "lanes": s.lanes,
                          "free_flow_kmh": s.free_flow_kmh, "bypass": s.bypass} for s in c.segments],
            "has_truth": self.mode != Mode.live,
            "runs": self.mode != Mode.live,
            "scenarios": [x for x in CATALOG if not (self.mode == Mode.hybrid and x["kind"] == "rain")],
            "max_scenarios": MAX_SCENARIOS,
            "weather_source": ("recorded series" if self.mode == Mode.hybrid else
                               "stochastic generator" if self.mode == Mode.simulation else "live ingestion"),
        }
