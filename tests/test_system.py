import hashlib
import json

import numpy as np
import pytest

from routetwin.contracts import Batch
from routetwin.corridor import load_corridor
from routetwin.runtime import Runtime
from routetwin.simulator import SimConfig, World
from routetwin.twin import TwinEngine
from routetwin.weather import SeriesWeather


def run(days, seed=7, script=False):
    cor = load_corridor()
    w = World(cor, SimConfig(seed=seed, demo_script=script))
    e = TwinEngine(cor)
    for _ in range(144 * days):
        e.ingest(w.step())
        e.evaluate(w.ts)
    return w, e


@pytest.fixture(scope="module")
def week():
    return run(10)


def test_simulator_messages_satisfy_contracts():
    w = World(load_corridor(), SimConfig(seed=1))
    msgs = []
    for _ in range(30):
        msgs += w.step()
    batch = Batch.model_validate({"messages": [m.model_dump() for m in msgs]})
    assert len(batch.messages) == len(msgs)


def test_twin_tracks_hidden_condition_truth(week):
    w, e = week
    snap = e.snapshot()
    err = [abs(s["ci"] - t) for s, t in zip(snap["segments"], w.snapshot_truth()["ci"])]
    assert np.mean(err) < 1.5 and max(err) < 4.0


def test_twin_finds_the_true_potholes_without_false_ones():
    w, e = run(30)
    snap = e.snapshot()
    assert [len(p) for p in w.potholes] == [len(s["potholes"]) for s in snap["segments"]]


def test_closure_raises_alarm_and_advisory_and_return_to_normal():
    rt = Runtime("simulation", demo_script=False)
    rt.advance(200)
    rt.trigger("closure", segment_id=7, hours=2)
    rt.advance(8)
    s = rt.snapshot()
    assert any(a["tag"] == "S08.ROAD_CLOSURE" for a in s["alarms"])
    assert s["segments"][7]["status"] == "red"
    assert any(a["segment_id"] == 7 for a in s["advisories"])
    rt.advance(30)
    s = rt.snapshot()
    a = next(a for a in s["alarms"] if a["tag"] == "S08.ROAD_CLOSURE")
    assert a["state"] == "rtn_unack"


def test_recurrent_bottleneck_slows_traffic_without_any_incident():
    rt = Runtime("simulation", demo_script=False)
    rt.world.cfg.random_incidents = False
    slow = False
    for _ in range(144 * 3):
        rt.advance(1)
        slow = slow or any(x["status"] == "amber" for x in rt.snapshot()["segments"])
    assert slow


def test_incidents_drive_segments_red_and_raise_congestion_alarms():
    rt = Runtime("simulation", demo_script=False)
    saw_red, saw_alarm = False, False
    for _ in range(144 * 10):
        rt.advance(1)
        if rt.engine.ts % 600 == 0:
            s = rt.engine.snapshot()
            saw_red = saw_red or any(x["status"] == "red" for x in s["segments"])
            saw_alarm = saw_alarm or any(a["type"] == "CONGESTION_RED" for a in s["alarms"])
    assert saw_red and saw_alarm


def test_overload_raises_alarm_and_accelerates_damage():
    rt = Runtime("simulation", demo_script=False)
    rt.advance(144 * 2)
    d0 = rt.world.D.copy()
    rt.advance(144 * 3)
    base = (rt.world.D - d0).sum()
    rt2 = Runtime("simulation", demo_script=False)
    rt2.advance(144 * 2)
    rt2.trigger("overload", mult=1.35, days=5)
    d1 = rt2.world.D.copy()
    rt2.advance(144 * 3)
    over = (rt2.world.D - d1).sum()
    assert over > 2.0 * base
    assert any(a["type"] == "OVERLOAD" for a in rt2.snapshot()["alarms"])


def test_maintenance_resets_twin_and_world():
    rt = Runtime("simulation", demo_script=False)
    rt.advance(144 * 3)
    worst = int(np.argmin(rt.world.ci_true()))
    rt.work_order(worst, "resurface")
    rt.advance(2)
    s = rt.snapshot(include_truth=True)
    assert s["truth"]["ci"][worst] > 90 and s["segments"][worst]["ci"] > 85
    assert s["segments"][worst]["potholes"] == []


def test_determinism_same_seed_same_state():
    def digest():
        w, e = run(3, seed=11, script=True)
        return hashlib.sha256(json.dumps(e.snapshot(), sort_keys=True, default=str).encode()).hexdigest()
    assert digest() == digest()


def test_sensor_outage_marks_segment_stale_and_alarms():
    rt = Runtime("simulation", demo_script=False)
    rt.advance(50)
    rt.trigger("sensor_outage", segment_id=4, ticks=40)
    rt.advance(10)
    s = rt.snapshot()
    assert s["segments"][4]["stale"]
    assert any(a["tag"] == "S05.SENSOR_STALE" for a in s["alarms"])


def test_hybrid_requires_recorded_weather_and_uses_it(tmp_path):
    with pytest.raises(FileNotFoundError):
        Runtime("hybrid", operator_token="t", weather_file=tmp_path / "missing.json")
    f = tmp_path / "w.json"
    f.write_text(json.dumps({"source": "test", "hourly": {"precipitation": [5.0] * 48, "temperature_2m": [31.0] * 48}}))
    rt = Runtime("hybrid", operator_token="t", weather_file=f)
    rt.advance(6)
    assert rt.snapshot()["weather"]["rain_mm_h"] == 5.0
    with pytest.raises(ValueError):
        rt.trigger("rain", hours=3)


def test_non_simulation_modes_refuse_to_start_unsecured():
    with pytest.raises(RuntimeError):
        Runtime("live", ingest_key="k")                 # no operator token
    with pytest.raises(RuntimeError):
        Runtime("live", operator_token="t")             # no ingest key


def test_series_weather_validation():
    with pytest.raises(ValueError):
        SeriesWeather([1.0], [])
