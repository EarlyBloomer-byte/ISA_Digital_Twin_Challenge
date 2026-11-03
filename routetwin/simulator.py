"""Simulated world: the hidden ground truth behind the sensors.

The twin never reads World state directly; it only receives contract messages.
World state is exposed separately (snapshot_truth) so tests and the dashboard
can compare the twin's estimates against ground truth - verification, not
validation: agreement here shows the twin implements its models correctly, not
that the models match real Nigerian roads.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import pavement as pv
from .contracts import (IncidentReport, MaintenanceEvent, ProbeObservation, SegmentObservation,
                        VehiclePosition, WeatherObservation)
from .corridor import Corridor
from .weather import InternalWeather

MAX_SCENARIOS = 3
SEGMENT_KINDS = ("closure", "accident", "sensor_outage")
SCENARIO_LABELS = {"rain": "Heavy rain", "overload": "Overloaded trucks", "surge": "Traffic surge",
                   "closure": "Road closure", "accident": "Accident", "sensor_outage": "Sensor outage"}
KJ_PER_LANE = 110.0        # jam density, veh/km/lane (illustrative)
CAP_PER_LANE = 1800.0      # veh/h/lane (illustrative)
DESIGN_YEARS = 8.0


@dataclass
class SimConfig:
    seed: int = 42
    tick_s: int = 600
    substeps: int = 4
    start_doy: int = 121
    n_trucks: int = 24
    demand_peak_vph: float = 3000.0
    loaded_fraction: float = 0.6
    probe_sigma: float = 0.6
    pothole_hazard: float = 3e-4
    pothole_detect_p: float = 0.7
    pothole_false_p: float = 0.02
    random_incidents: bool = True
    demo_script: bool = False
    # Optional model mismatch for validation runs (defaults leave the truth model identical to the twin's)
    initial_potholes: bool = False   # worn sections start with potholes already present (dashboard runs)
    wear_range: tuple = (0.25, 0.85)  # range of the initial damage of each segment
    damage_exponent: float = 4.0     # true load-damage exponent (the twin and the WIM stations assume 4)
    iri_beta: float | None = None    # true IRI(D) exponent (twin assumes 1.3)
    iri_span: float | None = None    # true IRI(D) span in m/km (twin assumes 7)


def _diurnal(hour: float, d: int) -> float:
    peak_am, peak_pm = (0.7, 1.0) if d == 0 else (1.0, 0.7)
    g = lambda c, w: math.exp(-0.5 * ((hour - c) / w) ** 2)
    return 0.12 + peak_am * g(7.0, 1.8) + peak_pm * g(17.0, 2.0) + 0.25 * g(12.5, 3.0)


def _truck_fraction(hour: float) -> float:
    return 0.22 + 0.18 * (0.5 + 0.5 * math.cos(2 * math.pi * (hour - 1.0) / 24.0))


class World:
    def __init__(self, corridor: Corridor, cfg: SimConfig | None = None, weather=None):
        self.cor = corridor
        self.cfg = cfg or SimConfig()
        c = self.cfg
        self.rng_env = np.random.default_rng(c.seed)
        self.rng_pav = np.random.default_rng(c.seed + 1)
        self.rng_obs = np.random.default_rng(c.seed + 2)
        self.weather = weather or InternalWeather(self.rng_env, c.start_doy, c.tick_s)
        n = corridor.n
        segs = corridor.segments
        self.L = np.array([s.length_km for s in segs])
        self.lanes = np.array([s.lanes for s in segs], dtype=float)
        self.vf0 = np.array([s.free_flow_kmh for s in segs], dtype=float)
        self.Q0 = CAP_PER_LANE * self.lanes * np.array([s.capacity_factor for s in segs])
        self.kj = KJ_PER_LANE * self.lanes
        self.n_veh = np.zeros((2, n))
        self.n_veh[:] = 0.02 * self.kj * self.L
        # hidden pavement truth
        self.D = self.rng_pav.uniform(c.wear_range[0], c.wear_range[1], n)
        self.theta = np.exp(self.rng_pav.normal(0.0, 0.35, n))
        self.potholes: list[list[float]] = [[] for _ in range(n)]
        if c.initial_potholes:  # a worn road already has potholes: expected number grows with wear and segment length
            ci0 = pv.condition_index(self.D)
            for i in range(n):
                if ci0[i] < 65.0:
                    k = int(self.rng_pav.poisson(2.5 * ((65.0 - ci0[i]) / 65.0) ** 2 * (self.L[i] / 8.0)))
                    self.potholes[i] = [float(x) for x in self.rng_pav.uniform(0, self.L[i] * 1000.0, k)]
        self.wet = 0.0
        # incidents: capacity multiplier and remaining ticks per (dir, segment)
        self.inc_factor = np.ones((2, n))
        self.inc_left = np.zeros((2, n), dtype=int)
        self.inc_reported = np.zeros((2, n), dtype=bool)
        self.inc_kind: dict[tuple[int, int], str] = {}
        self.sensor_out_left = np.zeros(n, dtype=int)
        self.overload_mult = 1.0
        self.overload_until = -1.0
        self.surge = 1.0
        self.surge_until = -1.0
        self.scen: list[dict] = []
        self._sid = 1
        self.ts = 0.0
        self.tick = 0
        self.rain = 0.0
        self.air = 28.0
        self.truth_history: list[list[float]] = []
        self.speed_truth = np.tile(self.vf0, (2, 1))
        self._pending_reports: list[IncidentReport] = []
        self.repairs: list[tuple[float, int, str]] = []
        # Design traffic -> nominal ESAL; shared by world and twin via corridor.design_esal
        self._init_fleet()
        self._script = self._build_script() if c.demo_script else []

    # ---------------------------------------------------------------- fleet
    def _init_fleet(self):
        c, rng = self.cfg, self.rng_env
        self.f_pos = rng.uniform(0, self.cor.length_km, c.n_trucks)
        self.f_dir = rng.integers(0, 2, c.n_trucks)
        self.f_gvw = np.where(rng.random(c.n_trucks) < c.loaded_fraction,
                              rng.normal(34, 5, c.n_trucks), rng.normal(16, 3, c.n_trucks)).clip(8, 60)
        self.f_dwell = np.zeros(c.n_trucks, dtype=int)
        self.f_bias = rng.normal(0.0, 0.2, c.n_trucks)  # per-vehicle IMU bias (m/km)
        self.f_seg = np.array([self.cor.locate_chainage(p)[2] for p in self.f_pos])

    # ---------------------------------------------------------------- scripted demo
    def _build_script(self):
        day = 86400.0
        return [
            (4 * day, "closure", {"segment_id": 7, "hours": 5}),
            (12 * day, "overload", {"mult": 1.35, "days": 10}),
            (22 * day, "rain", {"hours": 72}),
            (30 * day, "sensor_outage", {"segment_id": 4, "ticks": 90}),
            (40 * day, "closure", {"segment_id": 1, "hours": 4}),
        ]

    def trigger(self, kind: str, **kw):
        if kind == "closure":
            sid, hours = int(kw["segment_id"]), float(kw.get("hours", 4))
            for d in (0, 1):
                self.inc_factor[d, sid] = 0.02
                self.inc_left[d, sid] = int(hours * 3600 / self.cfg.tick_s)
                self.inc_reported[d, sid] = True
                self.inc_kind[(d, sid)] = "closure"
            self._pending_reports.append(IncidentReport(
                ts=self.ts, source="sim_report", segment_id=sid, kind="closure", severity=1.0, active=True))
        elif kind == "accident":
            sid, d = int(kw["segment_id"]), int(kw.get("direction", 0))
            self.inc_factor[d, sid] = 0.25
            self.inc_left[d, sid] = int(kw.get("hours", 3) * 3600 / self.cfg.tick_s)
            self.inc_kind[(d, sid)] = "accident"
            self.inc_reported[d, sid] = True
            self._pending_reports.append(IncidentReport(
                ts=self.ts, source="sim_report", segment_id=sid, kind="accident", severity=0.75, active=True))
        elif kind == "overload":
            self.overload_mult = float(kw.get("mult", 1.3))
            self.overload_until = self.ts + float(kw.get("days", 7)) * 86400.0
        elif kind == "rain":
            self.weather.force_rain(self.ts + float(kw.get("hours", 24)) * 3600.0, float(kw.get("intensity", 8.0)))
        elif kind == "sensor_outage":
            self.sensor_out_left[int(kw["segment_id"])] = int(kw.get("ticks", 60))
        else:
            raise ValueError(f"unknown scenario '{kind}'")

    # ---------------------------------------------------------------- operator scenarios (at most three at once)
    def active_scenarios(self) -> list[dict]:
        return [x for x in self.scen if x["end"] > self.ts]

    def scenario_status(self) -> list[dict]:
        return [{"id": x["id"], "kind": x["kind"], "label": x["label"], "remaining_h": (x["end"] - self.ts) / 3600.0}
                for x in self.active_scenarios()]

    def add_scenario(self, kind: str, **kw):
        """Start a scenario with sensible defaults. At most MAX_SCENARIOS may be active; the same kind cannot repeat."""
        if kind not in SCENARIO_LABELS:
            raise ValueError("Unknown scenario")
        act = self.active_scenarios()
        if len(act) >= MAX_SCENARIOS:
            raise ValueError("A maximum of three scenarios can be active at once")
        if any(x["kind"] == kind for x in act):
            raise ValueError(f"{SCENARIO_LABELS[kind]} is already active")
        if kind == "rain" and not isinstance(self.weather, InternalWeather):
            raise ValueError("Rain is driven by recorded weather in hybrid mode")
        n, ts, tick = self.cor.n, self.ts, self.cfg.tick_s
        seg = None
        if kind in SEGMENT_KINDS:
            sid = kw.get("segment_id")
            seg = int(self.rng_env.integers(0, n)) if sid in (None, "random") else int(sid)
            if not 0 <= seg < n:
                raise ValueError("Unknown segment")
        if kind == "closure":
            hours = float(kw.get("hours") or 12); self.trigger("closure", segment_id=seg, hours=hours); end = ts + hours * 3600
        elif kind == "accident":
            d = kw.get("direction"); d = int(self.rng_env.integers(0, 2)) if d is None else int(d)
            hours = float(kw.get("hours") or 3); self.trigger("accident", segment_id=seg, direction=d, hours=hours); end = ts + hours * 3600
        elif kind == "overload":
            self.trigger("overload", mult=float(kw.get("mult") or 1.35), days=float(kw.get("days") or 7)); end = self.overload_until
        elif kind == "surge":
            self.surge = float(kw.get("mult") or 1.3); end = self.surge_until = ts + float(kw.get("days") or 3) * 86400.0
        elif kind == "rain":
            hours = float(kw.get("hours") or 72); self.trigger("rain", hours=hours, intensity=float(kw.get("intensity") or 8.0)); end = ts + hours * 3600
        else:
            ticks = int(round(float(kw.get("hours") or 15) * 3600 / tick)); self.trigger("sensor_outage", segment_id=seg, ticks=ticks); end = ts + ticks * tick
        label = SCENARIO_LABELS[kind] + (f" \u00b7 S{seg + 1:02d}" if seg is not None else "")
        self.scen.append({"id": self._sid, "kind": kind, "label": label, "end": end})
        self._sid += 1

    # ---------------------------------------------------------------- maintenance
    def apply_maintenance(self, seg_id: int, action: str):
        if action == "patch":
            self.potholes[seg_id].clear()
            self.D[seg_id] = max(0.0, self.D[seg_id] - 0.03)
        elif action == "resurface":
            self.potholes[seg_id].clear()
            self.D[seg_id] = 0.05
        else:
            raise ValueError(action)
        self.repairs.append((self.ts, seg_id, action))

    # ---------------------------------------------------------------- physics
    def ci_true(self):
        return pv.condition_index(self.D)

    def _pavement_vf_factor(self):
        ci = self.ci_true()
        n_pot = np.array([len(p) for p in self.potholes])
        return (1.0 - 0.25 * (1.0 - ci / 100.0) ** 2) * (1.0 - np.minimum(0.25, 0.03 * n_pot))

    def _speeds(self, n_veh, vf, Q):
        k = np.maximum(n_veh / self.L, 1e-9)
        kc = Q / vf
        w = Q / np.maximum(self.kj - kc, 1e-6)
        v_cong = w * (self.kj - k) / k
        return np.where(k <= kc, vf, np.clip(v_cong, 2.0, vf))

    def step(self, emit: bool = True, emit_positions: bool = True):
        c = self.cfg
        dt_h = c.tick_s / 3600.0
        self.ts += c.tick_s
        self.tick += 1
        hour = (self.ts % 86400.0) / 3600.0
        n = self.cor.n
        while self._script and self.ts >= self._script[0][0]:
            _, kind, kw = self._script.pop(0)
            self.trigger(kind, **kw)
        if self.overload_mult != 1.0 and self.ts > self.overload_until:
            self.overload_mult = 1.0
        if self.surge != 1.0 and self.ts > self.surge_until:
            self.surge = 1.0

        # weather and wetness
        self.rain, self.air = self.weather.at(self.ts)
        self.wet = self.wet * math.exp(-dt_h / 24.0)
        self.wet += (1.0 - self.wet) * (1.0 - math.exp(-self.rain * dt_h / 2.0))
        solar = max(0.0, math.sin(math.pi * (hour - 6.0) / 12.0))
        pav_temp = self.air + 14.0 * solar * (0.3 if self.rain > 0 else 1.0)

        # incidents
        msgs: list = list(self._pending_reports)
        self._pending_reports.clear()
        if c.random_incidents:
            starts = self.rng_env.random((2, n)) < 4e-4
            for d, s in zip(*np.nonzero(starts & (self.inc_left == 0))):
                self.inc_factor[d, s] = float(self.rng_env.uniform(0.15, 0.6))
                self.inc_left[d, s] = int(self.rng_env.integers(6, 24))
                self.inc_kind[(int(d), int(s))] = "breakdown" if self.inc_factor[d, s] > 0.35 else "accident"
                self.inc_reported[d, s] = bool(self.rng_env.random() < 0.6)
                if self.inc_reported[d, s]:
                    msgs.append(IncidentReport(ts=self.ts, source="sim_report", segment_id=int(s),
                                               kind=self.inc_kind[(int(d), int(s))],
                                               severity=float(1 - self.inc_factor[d, s]), active=True))
        active = self.inc_left > 0
        self.inc_left[active] -= 1
        for d, s in zip(*np.nonzero(active & (self.inc_left == 0))):
            self.inc_factor[d, s] = 1.0
            if self.inc_reported[d, s]:
                msgs.append(IncidentReport(ts=self.ts, source="sim_report", segment_id=int(s),
                                           kind=self.inc_kind.get((int(d), int(s)), "breakdown"),
                                           severity=0.0, active=False))
            self.inc_reported[d, s] = False

        # traffic: cell-transmission model
        vf = self.vf0 * self._pavement_vf_factor() * (1.0 - min(0.3, 0.05 * self.rain))
        rain_cap = 1.0 - min(0.25, 0.04 * self.rain)
        sub_h = dt_h / c.substeps
        passed = np.zeros((2, n))
        speed_acc = np.zeros((2, n))
        for _ in range(c.substeps):
            for d in (0, 1):
                Q = self.Q0 * self.inc_factor[d] * rain_cap
                S = np.minimum(vf * self.n_veh[d] / self.L, Q)
                wv = Q / np.maximum(self.kj - Q / vf, 1e-6)
                R = np.minimum(Q, wv * (self.kj * self.L - self.n_veh[d]) / self.L)
                demand = c.demand_peak_vph * _diurnal(hour, d) * self.surge * (1 + 0.05 * self.rng_env.standard_normal())
                out = np.empty(n)
                inflow = np.empty(n)
                if d == 0:
                    out[:-1] = np.minimum(S[:-1], R[1:]); out[-1] = S[-1]
                    inflow[0] = min(demand, R[0]); inflow[1:] = out[:-1]
                else:
                    out[1:] = np.minimum(S[1:], R[:-1]); out[0] = S[0]
                    inflow[-1] = min(demand, R[-1]); inflow[:-1] = out[1:]
                self.n_veh[d] = np.clip(self.n_veh[d] + (inflow - out) * sub_h, 0.0, self.kj * self.L)
                passed[d] += out * sub_h
                speed_acc[d] += self._speeds(self.n_veh[d], vf, Q)
        speed = speed_acc / c.substeps
        self.speed_truth = speed

        # trucks, ESAL, damage
        tf = _truck_fraction(hour)
        trucks = passed * tf
        m = 40
        loaded = self.rng_pav.random((2, n, m)) < c.loaded_fraction
        gvw = np.where(loaded, self.rng_pav.normal(34, 6, (2, n, m)) * self.overload_mult,
                       self.rng_pav.normal(16, 3, (2, n, m))).clip(8, 75)
        esal_mean = pv.esal_per_truck(gvw).mean(axis=2)
        gvw_mean = gvw.mean(axis=2)
        if c.damage_exponent != 4.0:
            norm = float(pv.esal_per_truck(34.0)) / float(pv.esal_per_truck_p(34.0, c.damage_exponent))
            esal_dmg = pv.esal_per_truck_p(gvw, c.damage_exponent).mean(axis=2) * norm
        else:
            esal_dmg = esal_mean
        esal_tick = (trucks * esal_dmg).sum(axis=0)
        u = esal_tick * pv.temp_factor(pav_temp) * pv.wet_factor(self.wet) / self.cor.design_esal
        self.D = self.D + self.theta * u

        # pothole formation
        ci = self.ci_true()
        lam = c.pothole_hazard * np.maximum(0.0, (65.0 - ci) / 65.0) ** 2 * (1.0 + 4.0 * self.wet)
        for s in np.nonzero(self.rng_pav.random(n) < lam)[0]:
            self.potholes[s].append(float(self.rng_pav.uniform(0, self.L[s] * 1000.0)))

        if self.tick % 144 == 0:
            self.truth_history.append([self.ts] + [float(x) for x in self.ci_true()])

        # fleet movement and probes
        probes: list[ProbeObservation] = []
        pos_msgs: list[VehiclePosition] = []
        for i in range(c.n_trucks):
            if self.f_dwell[i] > 0:
                self.f_dwell[i] -= 1
                continue
            d = int(self.f_dir[i])
            sid = int(self.f_seg[i])
            v = float(speed[d, sid]) * float(self.rng_env.uniform(0.9, 1.0))
            step_km = v * dt_h
            new = self.f_pos[i] + (step_km if d == 0 else -step_km)
            if new >= self.cor.length_km or new <= 0.0:
                self.f_pos[i] = min(max(new, 0.0), self.cor.length_km - 1e-6)
                self.f_dir[i] = 1 - d
                self.f_dwell[i] = int(self.rng_env.integers(6, 18))
                self.f_gvw[i] = (self.rng_env.normal(34, 5) if self.rng_env.random() < c.loaded_fraction
                                 else self.rng_env.normal(16, 3))
                self.f_gvw[i] = float(np.clip(self.f_gvw[i], 8, 60))
            else:
                self.f_pos[i] = new
            new_seg = self.cor.locate_chainage(self.f_pos[i])[2]
            if new_seg != sid and emit:
                probes.append(self._probe(i, sid, v))
            self.f_seg[i] = new_seg
            if emit and emit_positions:
                lat, lon, _, _ = self.cor.locate_chainage(self.f_pos[i])
                pos_msgs.append(VehiclePosition(ts=self.ts, source="sim_gps", vehicle_id=f"T{i + 1:02d}",
                                                lat=lat, lon=lon, speed_kmh=max(v, 0.0), direction=d,
                                                gvw_t=float(self.f_gvw[i])))
        self.sensor_out_left[self.sensor_out_left > 0] -= 1
        if not emit:
            return []

        # sensor observations
        rng = self.rng_obs
        msgs.append(WeatherObservation(ts=self.ts, source="sim_weather", rain_mm_h=float(self.rain), air_temp_c=float(self.air)))
        for s in range(n):
            if self.sensor_out_left[s] > 0:
                continue
            for d in (0, 1):
                cnt = int(max(0, round(passed[d, s] * (1 + 0.03 * rng.standard_normal()))))
                tr = int(round(trucks[d, s]))
                spd = float(np.clip(speed[d, s] + 2.0 * rng.standard_normal(), 0.0, 150.0))
                msgs.append(SegmentObservation(
                    ts=self.ts, source=f"station_S{s + 1:02d}", segment_id=s, direction=d, window_s=float(c.tick_s),
                    vehicle_count=cnt, truck_count=tr, mean_speed_kmh=spd,
                    esal_per_truck=float(esal_mean[d, s] * math.exp(0.08 * rng.standard_normal())) if tr > 0 else None,
                    mean_truck_gvw_t=float(gvw_mean[d, s] * (1 + 0.03 * rng.standard_normal())) if tr > 0 else None,
                    pavement_temp_c=float(pav_temp + 0.5 * rng.standard_normal())))
        msgs.extend(probes)
        msgs.extend(pos_msgs)
        return msgs

    def _iri_true(self, d) -> float:
        c = self.cfg
        if c.iri_beta is None and c.iri_span is None:
            return float(pv.iri_from_damage(d))
        beta = c.iri_beta if c.iri_beta is not None else pv.BETA
        span = c.iri_span if c.iri_span is not None else pv.IRI_SPAN
        return float(pv.IRI_NEW + span * min(max(d, 0.0), 1.35) ** beta)

    def _probe(self, i: int, sid: int, v: float) -> ProbeObservation:
        c, rng = self.cfg, self.rng_obs
        iri = self._iri_true(self.D[sid]) + self.f_bias[i] + c.probe_sigma * rng.standard_normal()
        impacts = [p + float(rng.normal(0, 15)) for p in self.potholes[sid] if rng.random() < c.pothole_detect_p]
        if rng.random() < c.pothole_false_p:
            impacts.append(float(rng.uniform(0, self.L[sid] * 1000.0)))
        impacts = [min(max(p, 0.0), float(self.L[sid] * 1000.0)) for p in impacts]
        return ProbeObservation(ts=self.ts, source=f"imu_T{i + 1:02d}", segment_id=sid, vehicle_id=f"T{i + 1:02d}",
                                iri_m_per_km=float(np.clip(iri, 0.3, 25.0)), speed_kmh=max(v, 1.0), impacts_m=impacts)

    # ---------------------------------------------------------------- ground truth for verification
    def snapshot_truth(self) -> dict:
        ci = self.ci_true()
        return {
            "ci": [float(x) for x in ci],
            "damage": [float(x) for x in self.D],
            "theta": [float(x) for x in self.theta],
            "potholes": [[float(p) for p in ph] for ph in self.potholes],
            "speed": [[float(x) for x in row] for row in self.speed_truth],
            "rain_mm_h": float(self.rain),
            "wetness": float(self.wet),
            "overload_mult": float(self.overload_mult),
        }
