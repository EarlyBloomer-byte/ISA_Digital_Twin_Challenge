"""Example telemetry client for live mode: posts an HMAC-signed batch to /api/ingest.

  ROUTETWIN_INGEST_KEY=secret python scripts/live_client_example.py http://127.0.0.1:8000
"""
import json
import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from routetwin.security import sign  # noqa: E402


def main(base: str):
    key = os.environ["ROUTETWIN_INGEST_KEY"]
    now = time.time()
    batch = {"messages": [
        {"type": "segment_obs", "ts": now, "source": "station_S08", "segment_id": 7, "direction": 0,
         "window_s": 600, "vehicle_count": 420, "truck_count": 130, "mean_speed_kmh": 62.0,
         "esal_per_truck": 2.1, "mean_truck_gvw_t": 31.0, "pavement_temp_c": 41.5},
        {"type": "probe_obs", "ts": now, "source": "imu_demo", "segment_id": 7, "vehicle_id": "DEMO1",
         "iri_m_per_km": 5.2, "speed_kmh": 70.0, "impacts_m": [2100.0]},
    ]}
    body = json.dumps(batch).encode()
    ts = str(now)
    r = httpx.post(f"{base}/api/ingest", content=body, headers={
        "Content-Type": "application/json", "X-Timestamp": ts, "X-Signature": sign(key, ts, body)})
    print(r.status_code, r.text)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000")
