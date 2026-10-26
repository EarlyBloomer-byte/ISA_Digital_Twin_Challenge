import json
import time

import pytest
from fastapi.testclient import TestClient

from routetwin.api import create_app
from routetwin.runtime import Runtime
from routetwin.security import sign


@pytest.fixture()
def sim():
    rt = Runtime("simulation", demo_script=False)
    rt.advance(150)
    with TestClient(create_app(rt)) as c:
        yield c, rt


def test_state_config_history_and_static(sim):
    c, _ = sim
    assert c.get("/healthz").json()["mode"] == "simulation"
    assert len(c.get("/api/config").json()["segments"]) == 13
    s = c.get("/api/state?truth=true").json()
    assert "truth" in s and len(s["segments"]) == 13
    assert "truth" not in c.get("/api/state").json()
    assert c.get("/api/segment/2/history").status_code == 200
    assert c.get("/api/segment/99/history").status_code == 404
    assert c.get("/").status_code == 200 and "RouteTwin" in c.get("/").text


def test_scenario_validation_and_ack(sim):
    c, rt = sim
    assert c.post("/api/scenario", json={"kind": "closure"}).status_code == 422
    assert c.post("/api/scenario", json={"kind": "closure", "segment_id": 99}).status_code == 404
    assert c.post("/api/scenario", json={"kind": "bogus"}).status_code == 422
    assert c.post("/api/scenario", json={"kind": "closure", "segment_id": 3, "hours": 2}).status_code == 200
    rt.advance(6)
    alarm = c.get("/api/state").json()["alarms"][0]
    assert c.post(f"/api/alarms/{alarm['id']}/ack").status_code == 200
    assert c.post("/api/alarms/999999/ack").status_code == 404
    assert c.post("/api/workorder", json={"segment_id": 3, "action": "patch"}).status_code == 200
    assert c.post("/api/workorder", json={"segment_id": 3, "action": "demolish"}).status_code == 422


def test_ingest_disabled_outside_live_mode(sim):
    c, _ = sim
    assert c.post("/api/ingest", content=b"{}").status_code == 404


def test_live_mode_signed_ingestion_and_operator_auth(tmp_path):
    rt = Runtime("live", ingest_key="k3y", operator_token="op", audit_path=tmp_path / "audit.log")
    with TestClient(create_app(rt)) as c:
        now = time.time()
        batch = {"messages": [{"type": "segment_obs", "ts": now, "source": "st", "segment_id": 7, "direction": 0,
                               "window_s": 600, "vehicle_count": 300, "truck_count": 90, "mean_speed_kmh": 6.0,
                               "esal_per_truck": 2.0, "pavement_temp_c": 40.0}] * 3}
        body = json.dumps(batch).encode()
        ts = str(now)
        h = {"X-Timestamp": ts, "X-Signature": sign("k3y", ts, body), "Content-Type": "application/json"}
        assert c.post("/api/ingest", content=body, headers=h).json() == {"accepted": 3}
        assert c.post("/api/ingest", content=body, headers=h).status_code == 401       # replay
        bad = {**h, "X-Signature": "0" * 64}
        assert c.post("/api/ingest", content=body, headers=bad).status_code == 401
        ts2 = str(time.time())
        garbage = b'{"messages":[{"type":"segment_obs"}]}'
        h2 = {"X-Timestamp": ts2, "X-Signature": sign("k3y", ts2, garbage)}
        assert c.post("/api/ingest", content=garbage, headers=h2).status_code == 422
        # operator endpoints need the token
        assert c.post("/api/control", json={"paused": True}).status_code == 401
        assert c.post("/api/control", json={"paused": True}, headers={"X-Operator-Token": "op"}).status_code == 200
        rt.evaluate_live(); rt.evaluate_live(); rt.evaluate_live()
        assert c.get("/api/state").json()["segments"][7]["speed"][0] is not None
    log = (tmp_path / "audit.log").read_text()
    assert "ingest_rejected" in log and "auth_denied" in log
