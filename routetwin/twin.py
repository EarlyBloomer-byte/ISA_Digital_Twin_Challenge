"""Twin engine: consumes contract messages, maintains road and fleet state, raises alarms, advises.

The engine is source-agnostic. It is fed by the simulator (simulation/hybrid) or by the
signed ingestion API (live), through the same message contracts.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from . import pavement as pv
from .alarms import AlarmDef, AlarmManager
from .contracts import (IncidentReport, MaintenanceEvent, ProbeObservation, SegmentObservation,
                        VehiclePosition, WeatherObservation)
from .corridor import Corridor
from .decision import maintenance_queue, traffic_advisories
from .estimator import PavementEKF


@dataclass
class TwinConfig:
    red_kmh: float = 10.0
    red_clear_kmh: float = 15.0
    amber_kmh: float = 30.0
    red_on_delay: int = 2
    ci_critical: float = 45.0
    ci_clear: float = 50.0
    rul_warn_days: float = 30.0
    overload_esal: float = 2.6
    overload_clear: float = 2.1
    overload_on_delay: int = 6
    stale_after_s: float = 1800.0
    speed_alpha: float = 0.4
    pothole_merge_m: float = 40.0
    pothole_confirm_hits: int = 3
    pothole_confirm_rate: float = 0.35
    pothole_reject_rate: float = 0.2
    pothole_reject_after_passes: int = 12
    spillback_reach: int = 4
    auto_archive_rtn_s: float | None = None
    unconfirmed_prune_s: float = 3 * 86400.0
    prior_damage: float = 0.5
    prior_sd_damage: float = 0.25


DEFS = {
    "CONGESTION_RED": AlarmDef("CONGESTION_RED", "high", 2, "Severe congestion",
                               "Trucks stranded; delivery delay; queue spillback upstream",
                               "Notify dispatchers; apply hold or bypass advisories"),
    "ROAD_CLOSURE": AlarmDef("ROAD_CLOSURE", "high", 1, "Road closure or blocking incident reported",
                             "Corridor blocked; trucks cannot pass",
                             "Divert trucks at the last bypass; confirm with traffic authority"),
    "CONDITION_CRITICAL": AlarmDef("CONDITION_CRITICAL", "high", 3, "Pavement condition critical",
                                   "Pothole formation; vehicle damage; speed loss",
                                   "Schedule resurfacing work order"),
    "MAINT_DUE": AlarmDef("MAINT_DUE", "medium", 3, "Maintenance due within planning horizon",
                          "Condition will cross the critical threshold soon", "Plan a work order"),
    "POTHOLE_FORMED": AlarmDef("POTHOLE_FORMED", "medium", 1, "Pothole confirmed by probe vehicles",
                               "Tyre/suspension damage risk; local slowdown", "Dispatch patching crew to the coordinates"),
    "OVERLOAD": AlarmDef("OVERLOAD", "medium", 6, "Sustained overloaded trucks (weigh-in-motion)",
                         "Pavement damage rate multiplied (fourth-power law)", "Notify axle-load enforcement"),
    "SENSOR_STALE": AlarmDef("SENSOR_STALE", "low", 1, "Segment station data stale",
                             "Estimates for this segment degrade to model-only", "Check station power/communications"),
}


@dataclass
class DirState:
    speed: float | None = None
    flow_vph: float | None = None
    trucks_vph: float | None = None


@dataclass
class SegState:
    id: int
    ekf: PavementEKF
    dirs: list[DirState] = field(default_factory=lambda: [DirState(), DirState()])
    pav_temp: float | None = None
    esal_ewma: float | None = None
    gvw_ewma: float | None = None
    last_obs_ts: float | None = None
    u_acc: float = 0.0
    rate_u_day: float | None = None
    potholes: list[dict] = field(default_factory=list)
    next_pothole_id: int = 1
    incident: dict | None = None
    ci_history: list[tuple[float, float, float]] = field(default_factory=list)


class TwinEngine:
    def __init__(self, corridor: Corridor, cfg: TwinConfig | None = None, mode: str = "simulation"):
        self.cor = corridor
        self.cfg = cfg or TwinConfig()
        self.mode = mode
        self.segs = [SegState(s.id, PavementEKF(self.cfg.prior_damage, self.cfg.prior_sd_damage)) for s in corridor.segments]
        self.alarms = AlarmManager(auto_archive_rtn_s=self.cfg.auto_archive_rtn_s)
        self.fleet: dict[str, dict] = {}
        self.wet = 0.0
        self.rain = 0.0
        self.air = None
        self._last_weather_ts: float | None = None
        self.ts = 0.0
        self._last_eval_ts: float | None = None
        self._last_daily = -1
        self.advisories: list[dict] = []
        self.maintenance: list[dict] = []
        self.counters = {"messages": 0, "probe_rejected": 0}

    # ------------------------------------------------------------------ ingest
    def ingest(self, msgs) -> None:
        for m in msgs:
            self.counters["messages"] += 1
            t = m.type
            if t == "segment_obs":
                self._segment_obs(m)
            elif t == "probe_obs":
                self._probe_obs(m)
            elif t == "vehicle_pos":
                self._vehicle_pos(m)
            elif t == "weather_obs":
                self._weather_obs(m)
            elif t == "incident":
                self._incident(m)
            elif t == "maintenance":
                self._maintenance(m)
            self.ts = max(self.ts, m.ts)

    def _segment_obs(self, m: SegmentObservation):
        if m.segment_id >= len(self.segs):
            return
        s = self.segs[m.segment_id]
        a = self.cfg.speed_alpha
        ds = s.dirs[m.direction]
        ds.speed = m.mean_speed_kmh if ds.speed is None else a * m.mean_speed_kmh + (1 - a) * ds.speed
        ds.flow_vph = m.vehicle_count * 3600.0 / m.window_s
        ds.trucks_vph = m.truck_count * 3600.0 / m.window_s
        if m.pavement_temp_c is not None:
            s.pav_temp = m.pavement_temp_c
        if m.esal_per_truck is not None and m.truck_count > 0:
            s.esal_ewma = m.esal_per_truck if s.esal_ewma is None else 0.15 * m.esal_per_truck + 0.85 * s.esal_ewma
            if m.mean_truck_gvw_t is not None:
                s.gvw_ewma = m.mean_truck_gvw_t if s.gvw_ewma is None else 0.15 * m.mean_truck_gvw_t + 0.85 * s.gvw_ewma
            esal = m.truck_count * m.esal_per_truck
            temp = s.pav_temp if s.pav_temp is not None else 30.0
            u = esal * float(pv.temp_factor(temp)) * float(pv.wet_factor(self.wet)) / self.cor.design_esal
            s.ekf.predict(u)
            s.u_acc += u
        s.last_obs_ts = m.ts

    def _probe_obs(self, m: ProbeObservation):
        if m.segment_id >= len(self.segs):
            return
        s = self.segs[m.segment_id]
        if not s.ekf.update(m.iri_m_per_km):
            self.counters["probe_rejected"] += 1
        matched: set[int] = set()
        for c in m.impacts_m:
            near = next((p for p in s.potholes
                         if p["id"] not in matched and abs(p["chainage_m"] - c) <= self.cfg.pothole_merge_m), None)
            if near:
                near["chainage_m"] = (near["chainage_m"] * near["hits"] + c) / (near["hits"] + 1)
                near["hits"] += 1
                near["last_ts"] = m.ts
                matched.add(near["id"])
            else:
                p = {"id": s.next_pothole_id, "chainage_m": c, "hits": 1, "passes": 0, "confirmed": False,
                     "first_ts": m.ts, "last_ts": m.ts, "alarmed": False}
                s.next_pothole_id += 1
                s.potholes.append(p)
                matched.add(p["id"])
        # Persistence filter: a real pothole is hit on most passes; spurious impacts are not.
        for p in s.potholes:
            p["passes"] += 1
            if (not p["confirmed"] and p["hits"] >= self.cfg.pothole_confirm_hits
                    and p["hits"] / p["passes"] >= self.cfg.pothole_confirm_rate):
                p["confirmed"] = True

    def _vehicle_pos(self, m: VehiclePosition):
        ch, sid = self.cor.project(m.lat, m.lon)
        self.fleet[m.vehicle_id] = {"vehicle_id": m.vehicle_id, "lat": m.lat, "lon": m.lon, "speed": m.speed_kmh,
                                    "direction": m.direction, "gvw_t": m.gvw_t, "chainage_km": ch,
                                    "segment_id": sid, "ts": m.ts}

    def _weather_obs(self, m: WeatherObservation):
        dt_h = 0.0 if self._last_weather_ts is None else max(0.0, (m.ts - self._last_weather_ts) / 3600.0)
        self._last_weather_ts = m.ts
        self.wet *= math.exp(-dt_h / 24.0)
        self.wet += (1.0 - self.wet) * (1.0 - math.exp(-m.rain_mm_h * dt_h / 2.0))
        self.rain, self.air = m.rain_mm_h, m.air_temp_c

    def _incident(self, m: IncidentReport):
        if m.segment_id >= len(self.segs):
            return
        s = self.segs[m.segment_id]
        if m.active:
            s.incident = {"kind": m.kind, "severity": m.severity, "since": m.ts}
        elif s.incident and s.incident["kind"] == m.kind:
            s.incident = None

    def _maintenance(self, m: MaintenanceEvent):
        if m.segment_id >= len(self.segs):
            return
        s = self.segs[m.segment_id]
        for p in s.potholes:
            self.alarms.clear_event(f"S{s.id + 1:02d}.POTHOLE.{p['id']}", m.ts)
        s.potholes.clear()
        if m.action == "resurface":
            s.ekf.reset_after_maintenance(0.05)
        else:
            s.ekf.reset_after_maintenance(max(0.0, s.ekf.d - 0.03), sd=max(0.08, s.ekf.sd_d))

    # ------------------------------------------------------------------ evaluate
    def evaluate(self, ts: float) -> None:
        cfg, al = self.cfg, self.alarms
        self.ts = max(self.ts, ts)
        dt = None if self._last_eval_ts is None else max(ts - self._last_eval_ts, 1e-9)
        self._last_eval_ts = ts
        blocking_ids = [x.id for x in self.segs if x.incident and x.incident["severity"] >= 0.7]
        for s in self.segs:
            sid = s.id
            tag = lambda name: f"S{sid + 1:02d}.{name}"
            if dt:
                r = s.u_acc / dt * 86400.0
                s.rate_u_day = r if s.rate_u_day is None else 0.01 * r + 0.99 * s.rate_u_day
            s.u_acc = 0.0
            stale = s.last_obs_ts is not None and (ts - s.last_obs_ts) > cfg.stale_after_s
            speeds = [d.speed for d in s.dirs if d.speed is not None]
            vmin = min(speeds) if speeds else None
            closed = bool(s.incident and s.incident["kind"] == "closure" and s.incident["severity"] >= 0.9)
            blocking = bool(s.incident and s.incident["severity"] >= 0.7)

            al.evaluate(tag("SENSOR_STALE"), DEFS["SENSOR_STALE"], sid, ts, stale, not stale, setpoint="no data > 30 min")
            al.evaluate(tag("ROAD_CLOSURE"), DEFS["ROAD_CLOSURE"], sid, ts, blocking, not blocking,
                        value=s.incident["severity"] if s.incident else None, setpoint="incident severity >= 0.7")
            rising = vmin is not None and not stale
            al.evaluate(tag("CONGESTION_RED"), DEFS["CONGESTION_RED"], sid, ts,
                        rising and vmin < cfg.red_kmh, (not rising) or vmin > cfg.red_clear_kmh,
                        value=vmin, setpoint=f"speed < {cfg.red_kmh:.0f} km/h (clear > {cfg.red_clear_kmh:.0f})",
                        suppressed=blocking or closed or any(abs(sid - b) <= cfg.spillback_reach for b in blocking_ids))
            ci = float(pv.condition_index(s.ekf.d))
            crit_active = tag("CONDITION_CRITICAL") in al.active
            al.evaluate(tag("CONDITION_CRITICAL"), DEFS["CONDITION_CRITICAL"], sid, ts,
                        ci < cfg.ci_critical, ci > cfg.ci_clear, value=ci,
                        setpoint=f"CI < {cfg.ci_critical:.0f} (clear > {cfg.ci_clear:.0f})")
            rul = self._rul(s)
            crit_now = tag("CONDITION_CRITICAL") in al.active
            al.evaluate(tag("MAINT_DUE"), DEFS["MAINT_DUE"], sid, ts,
                        rul is not None and rul < cfg.rul_warn_days, rul is None or rul > cfg.rul_warn_days * 1.3,
                        value=rul, setpoint=f"RUL < {cfg.rul_warn_days:.0f} d", suppressed=crit_now)
            ov = s.esal_ewma is not None and not stale
            al.evaluate(tag("OVERLOAD"), DEFS["OVERLOAD"], sid, ts,
                        ov and s.esal_ewma > cfg.overload_esal, (not ov) or s.esal_ewma < cfg.overload_clear,
                        value=s.esal_ewma, setpoint=f"ESAL/truck > {cfg.overload_esal:.1f}", suppressed=stale)
            for p in s.potholes:
                if p["confirmed"] and not p["alarmed"]:
                    p["alarmed"] = True
                    lat, lon = self.cor.locate(sid, p["chainage_m"])
                    al.raise_event(tag(f"POTHOLE.{p['id']}"), DEFS["POTHOLE_FORMED"], sid, ts, value=p["chainage_m"],
                                   setpoint="persistent impact detections", lat=lat, lon=lon)
            s.potholes[:] = [p for p in s.potholes if p["confirmed"] or not (
                (p["passes"] >= cfg.pothole_reject_after_passes and p["hits"] / p["passes"] < cfg.pothole_reject_rate)
                or ts - p["last_ts"] > cfg.unconfirmed_prune_s)]
            day = int(ts // 86400)
            if day != self._last_daily:
                sd_ci = float(pv.condition_index(s.ekf.d - s.ekf.sd_d) - pv.condition_index(s.ekf.d + s.ekf.sd_d)) / 2
                s.ci_history.append((ts, ci, sd_ci))
        al.housekeeping(ts)
        day = int(ts // 86400)
        self._last_daily = day

    def _rul(self, s: SegState) -> float | None:
        if s.rate_u_day is None:
            return None
        rate = s.ekf.theta * s.rate_u_day
        if rate <= 1e-9:
            return None
        d_thr = float(pv.damage_from_ci(self.cfg.ci_critical))
        return float(min(max((d_thr - s.ekf.d) / rate, 0.0), 3650.0))

    # ------------------------------------------------------------------ outputs
    def snapshot(self) -> dict:
        cfg = self.cfg
        segs_out = []
        speeds, closed = {}, set()
        for s in self.segs:
            cs = self.cor.segments[s.id]
            ci = float(pv.condition_index(s.ekf.d))
            sd_ci = float(pv.condition_index(s.ekf.d - s.ekf.sd_d) - pv.condition_index(s.ekf.d + s.ekf.sd_d)) / 2
            v = [d.speed for d in s.dirs]
            speeds[s.id] = v
            stale = s.last_obs_ts is not None and (self.ts - s.last_obs_ts) > cfg.stale_after_s
            if s.incident and s.incident["kind"] == "closure" and s.incident["severity"] >= 0.9:
                closed.add(s.id)
            known = [x for x in v if x is not None]
            vmin = min(known) if known else None
            if stale or vmin is None:
                status = "unknown"
            elif s.id in closed or vmin < cfg.red_kmh:
                status = "red"
            elif vmin < cfg.amber_kmh:
                status = "amber"
            else:
                status = "normal"
            segs_out.append({
                "id": s.id, "name": cs.name, "length_km": cs.length_km, "lanes": cs.lanes,
                "ci": ci, "ci_sd": sd_ci, "damage": s.ekf.d, "damage_sd": s.ekf.sd_d,
                "theta": s.ekf.theta, "theta_sd": s.ekf.sd_theta,
                "iri": float(pv.iri_from_damage(s.ekf.d)), "rul_days": self._rul(s),
                "speed": v, "flow_vph": [d.flow_vph for d in s.dirs], "status": status, "stale": stale,
                "pav_temp": s.pav_temp, "esal_per_truck": s.esal_ewma, "gvw_t": s.gvw_ewma,
                "incident": s.incident, "probe_updates": s.ekf.updates,
                "potholes": [{"id": p["id"], "chainage_m": p["chainage_m"], "hits": p["hits"],
                              "confirmed": True,
                              "lat": self.cor.locate(s.id, p["chainage_m"])[0],
                              "lon": self.cor.locate(s.id, p["chainage_m"])[1]} for p in s.potholes
                             if p["confirmed"]],
            })
        fleet = sorted(self.fleet.values(), key=lambda f: f["vehicle_id"])
        self.advisories = traffic_advisories(self.cor, segs_out, closed)
        self.maintenance = maintenance_queue(segs_out)
        return {
            "ts": self.ts, "mode": self.mode,
            "weather": {"rain_mm_h": self.rain, "air_temp_c": self.air, "wetness": self.wet},
            "segments": segs_out, "fleet": fleet,
            "alarms": self.alarms.listing(), "kpi": self.alarms.kpis(self.ts),
            "advisories": self.advisories[:12], "maintenance": self.maintenance,
            "counters": self.counters,
        }
