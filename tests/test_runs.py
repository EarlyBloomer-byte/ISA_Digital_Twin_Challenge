import numpy as np
import pytest
from fastapi.testclient import TestClient

from routetwin.api import create_app
from routetwin.corridor import load_corridor
from routetwin.runtime import NoRun, Runtime
from routetwin.simulator import SimConfig, World


def fresh(seed):
    return World(load_corridor(), SimConfig(seed=seed, demo_script=False, initial_potholes=True, wear_range=(0.15, 0.75)))


def test_dashboard_runs_differ_by_seed_and_repeat_for_the_same_seed():
    a, a2, b = fresh(1), fresh(1), fresh(2)
    assert a.potholes == a2.potholes and np.allclose(a.D, a2.D)
    assert a.potholes != b.potholes or not np.allclose(a.D, b.D)


def test_potholes_can_be_none_one_or_several_and_land_on_different_segments():
    counts, where = set(), set()
    for seed in range(1, 61):
        for i, p in enumerate(fresh(seed).potholes):
            counts.add(len(p))
            if p:
                where.add(i)
    assert 0 in counts and 1 in counts and max(counts) >= 2
    assert len(where) >= 6


def test_default_world_is_unchanged_so_published_results_still_reproduce():
    w = World(load_corridor(), SimConfig(seed=42))
    assert all(len(p) == 0 for p in w.potholes)
    assert 0.25 <= w.D.min() and w.D.max() <= 0.85


def test_three_scenarios_together_and_a_fourth_is_refused():
    w = fresh(5)
    for kind in ("rain", "overload"):
        w.add_scenario(kind)
    w.add_scenario("closure", segment_id=3)
    assert len(w.scenario_status()) == 3
    with pytest.raises(ValueError, match="maximum of three"):
        w.add_scenario("surge")


def test_same_scenario_cannot_repeat_and_expired_scenarios_free_a_slot():
    w = fresh(6)
    w.add_scenario("closure", segment_id=2, hours=1)
    with pytest.raises(ValueError, match="already active"):
        w.add_scenario("closure", segment_id=5)
    for _ in range(8):
        w.step(emit=False)
    assert w.scenario_status() == []
    w.add_scenario("closure", segment_id=5, hours=1)


def test_random_segment_and_unknown_inputs():
    w = fresh(7)
    w.add_scenario("sensor_outage", segment_id="random")
    assert "S" in w.scenario_status()[0]["label"]
    with pytest.raises(ValueError):
        w.add_scenario("nonsense")
    with pytest.raises(ValueError):
        w.add_scenario("closure", segment_id=99)


def test_rain_and_overload_take_effect_together():
    w = fresh(9)
    w.add_scenario("rain", hours=48)
    w.add_scenario("overload", days=5)
    for _ in range(60):
        w.step(emit=False)
    assert w.rain > 0 and w.wet > 0.05 and w.overload_mult > 1.0


def test_traffic_surge_raises_flow():
    base, surge = fresh(11), fresh(11)
    surge.add_scenario("surge")
    flows = []
    for w in (base, surge):
        tot = 0.0
        for _ in range(60):
            w.step(emit=False)
            tot += float(w.n_veh.sum())
        flows.append(tot)
    assert flows[1] > flows[0]


def test_runtime_stop_and_fresh_start():
    rt = Runtime("simulation", autostart=False)
    assert not rt.running and rt.snapshot()["stopped"] is True
    with pytest.raises(NoRun):
        rt.add_scenario("rain")
    s1 = rt.start_run(seed=123, scenarios=[{"kind": "rain"}, {"kind": "overload"}])
    rt.advance(144 * 2)
    assert rt.snapshot()["clock"]["day"] > 1.9 and len(rt.snapshot()["run"]["scenarios"]) == 2
    rt.stop_run()
    assert rt.snapshot()["stopped"] is True
    rt.start_run(seed=124, scenarios=[])
    snap = rt.snapshot()
    assert snap["clock"]["day"] < 0.1 and snap["run"]["seed"] == 124 and s1 == 123


def test_runtime_random_seed_differs_between_runs():
    rt = Runtime("simulation", autostart=False)
    assert rt.start_run() != rt.start_run()


def test_runtime_refuses_more_than_three_and_rolls_back():
    rt = Runtime("simulation", autostart=False)
    four = [{"kind": k} for k in ("rain", "overload", "surge", "accident")]
    with pytest.raises(ValueError):
        rt.start_run(seed=1, scenarios=four)
    assert not rt.running


def test_advance_respects_time_budget():
    rt = Runtime("simulation", autostart=False)
    rt.start_run(seed=3)
    assert rt.advance(100000, budget_s=0.05) < 100000


def test_api_run_lifecycle_and_scenarios():
    rt = Runtime("simulation", autostart=False)
    with TestClient(create_app(rt)) as c:
        assert c.get("/api/state").json()["stopped"] is True
        cfg = c.get("/api/config").json()
        assert cfg["runs"] and cfg["max_scenarios"] == 3 and {x["kind"] for x in cfg["scenarios"]} >= {"rain", "surge", "closure"}
        assert c.post("/api/scenario", json={"kind": "rain"}).status_code == 409           # nothing running
        assert c.get("/api/segment/1/history").status_code == 409
        r = c.post("/api/run/start", json={"seed": "", "scenarios": [{"kind": "rain"}, {"kind": "overload"}, {"kind": "closure", "segment_id": "7"}]})
        assert r.status_code == 200 and isinstance(r.json()["seed"], int)
        s = c.get("/api/state").json()
        assert len(s["run"]["scenarios"]) == 3 and s["run"]["seed"] == r.json()["seed"]
        assert c.post("/api/scenario", json={"kind": "surge"}).status_code == 409           # fourth refused
        assert c.post("/api/run/stop").status_code == 200
        assert c.get("/api/state").json()["stopped"] is True


def test_api_run_start_validation():
    rt = Runtime("simulation", autostart=False)
    with TestClient(create_app(rt)) as c:
        four = [{"kind": k} for k in ("rain", "overload", "surge", "accident")]
        assert c.post("/api/run/start", json={"scenarios": four}).status_code == 400
        assert c.post("/api/run/start", json={"seed": "abc"}).status_code == 400
        assert c.post("/api/run/start", json={"scenarios": [{"kind": "closure", "segment_id": 99}]}).status_code == 400
        assert c.post("/api/run/start", json={"scenarios": [{"kind": "nope"}]}).status_code == 422
        assert c.post("/api/run/start", json={"seed": "42", "scenarios": []}).json()["seed"] == 42
        assert c.post("/api/control", json={"speed": 288}).status_code == 200


def test_live_mode_has_no_runs():
    rt = Runtime("live", ingest_key="k", operator_token="t")
    with TestClient(create_app(rt)) as c:
        assert c.get("/api/config").json()["runs"] is False
        assert c.post("/api/run/start", json={}, headers={"X-Operator-Token": "t"}).status_code == 400
