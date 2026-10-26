"""Runtime: wires a data mode (simulation / hybrid / live) to the twin engine."""
from __future__ import annotations

import threading
import time
from pathlib import Path

from .contracts import MaintenanceEvent, Mode
from .corridor import load_corridor
from .security import AuditLog, IngestVerifier
from .simulator import SimConfig, World
from .twin import TwinConfig, TwinEngine
from .weather import SeriesWeather

DEFAULT_WEATHER = Path(__file__).resolve().parent.parent / "data" / "field" / "weather_lagos_ibadan.json"


class Runtime:
    def __init__(self, mode: str | Mode = "simulation", seed: int = 42, corridor_path=None, weather_file=None,
                 demo_script: bool = True, audit_path=None, ingest_key: str | None = None,
                 operator_token: str | None = None, speed: int = 6):
        self.mode = Mode(mode)
        self.cor = load_corridor(corridor_path)
        self.operator_token = operator_token
        self.audit = AuditLog(audit_path)
        self.lock = threading.RLock()
        self.speed = speed
        self.paused = False
        self.world: World | None = None
        self.verifier: IngestVerifier | None = None

        if self.mode != Mode.simulation and not operator_token:
            raise RuntimeError("hybrid/live modes require ROUTETWIN_OPERATOR_TOKEN (control endpoints must be authenticated)")
        if self.mode == Mode.live:
            if not ingest_key:
                raise RuntimeError("live mode requires ROUTETWIN_INGEST_KEY for signed telemetry ingestion")
            self.verifier = IngestVerifier(ingest_key)

        tcfg = TwinConfig(auto_archive_rtn_s=6 * 3600.0 if self.mode != Mode.live else None)
        self.engine = TwinEngine(self.cor, tcfg, mode=self.mode.value)
        if self.mode in (Mode.simulation, Mode.hybrid):
            weather = SeriesWeather.from_file(weather_file or DEFAULT_WEATHER) if self.mode == Mode.hybrid else None
            self.world = World(self.cor, SimConfig(seed=seed, demo_script=demo_script and self.mode == Mode.simulation),
                               weather=weather)
        self._snap_cache: tuple[float, dict] | None = None

    # ---------------------------------------------------------------- stepping
    def advance(self, n: int = 1):
        if self.world is None:
            return
        with self.lock:
            for _ in range(n):
                self.engine.ingest(self.world.step())
                self.engine.evaluate(self.world.ts)

    def evaluate_live(self):
        with self.lock:
            self.engine.evaluate(time.time())

    # ---------------------------------------------------------------- operator actions
    def trigger(self, kind: str, **kw):
        if self.world is None:
            raise ValueError("scenarios exist only where a simulated world runs")
        if self.mode == Mode.hybrid and kind == "rain":
            raise ValueError("rain is driven by recorded weather in hybrid mode")
        with self.lock:
            self.world.trigger(kind, **kw)
        self.audit.write("scenario", kind=kind, **kw)

    def work_order(self, segment_id: int, action: str):
        if not 0 <= segment_id < self.cor.n:
            raise ValueError("unknown segment")
        with self.lock:
            ts = self.world.ts if self.world else time.time()
            if self.world:
                self.world.apply_maintenance(segment_id, action)
            self.engine.ingest([MaintenanceEvent(ts=ts, source="dashboard_work_order", segment_id=segment_id, action=action)])
        self.audit.write("work_order", segment_id=segment_id, action=action)

    def ack(self, alarm_id: int) -> bool:
        with self.lock:
            ok = self.engine.alarms.acknowledge(alarm_id, self.engine.ts)
        self.audit.write("ack", alarm_id=alarm_id, ok=ok)
        return ok

    def ack_all(self) -> int:
        with self.lock:
            n = self.engine.alarms.acknowledge_all(self.engine.ts)
        self.audit.write("ack_all", count=n)
        return n

    # ---------------------------------------------------------------- views
    def snapshot(self, include_truth: bool = False) -> dict:
        with self.lock:
            s = self.engine.snapshot()
            s["control"] = {"speed": self.speed, "paused": self.paused}
            s["clock"] = {"day": s["ts"] / 86400.0, "hour": (s["ts"] % 86400.0) / 3600.0}
            if include_truth and self.world is not None:
                s["truth"] = self.world.snapshot_truth()
            return s

    def history(self, segment_id: int) -> dict:
        with self.lock:
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
            "has_truth": self.world is not None,
            "weather_source": ("recorded series" if self.mode == Mode.hybrid else
                               "stochastic generator" if self.mode == Mode.simulation else "live ingestion"),
        }
