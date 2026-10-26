# RouteTwin NG

A digital twin of a **smart road**: the Lagos-Ibadan expressway modelled as thirteen instrumented segments whose
pavement condition, traffic state and maintenance needs are estimated continuously from sensor data and acted on
through alarms, reroute advice and a maintenance queue. Built for the ISA Nigeria Next-Gen Automation Challenge
(Digital Twin for Industrial Operations).

> **Read this first.** Nothing in this repository is field evidence. The sensors, traffic and pavement truth come
> from a seeded simulator, and every model constant is an illustrative placeholder. What *is* verified is that the
> twin implements its models correctly: it recovers hidden simulated pavement state, finds simulated potholes, and
> obeys its alarm and security rules (see `docs/standards_mapping.md` and `pytest`). Matching real Nigerian roads
> would need calibration data this project does not have.

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q              # 46 tests
python -m routetwin              # open http://127.0.0.1:8000
```

Docker: `docker compose up --build`. Make targets: `make test demo compare`.

The dashboard shows a 3D corridor (drag, scroll, click a segment), alarms with acknowledgement, reroute advice,
a ranked maintenance queue with work orders, and a per-segment panel with a condition-index history chart.
The *Scenarios* menu injects closures, accidents, overloaded trucks, heavy rain and sensor outages.
Tick *Show simulator ground truth* to overlay the hidden truth on the chart and the 3D view.

## What is being twinned

| Physical asset | Sensors (simulated) | Model | Decisions supported |
|---|---|---|---|
| A pavement segment (4.9 to 14.5 km, 2 or 3 lanes per direction) | Roadside station per segment: vehicle count, truck count, mean speed, weigh-in-motion ESAL per truck, pavement temperature. Roughness observations from passing instrumented trucks (IMU-derived IRI and impact events) | Load-driven damage (fourth-power ESAL law with temperature and moisture factors), condition index, IRI, remaining life; cell-transmission traffic model in the simulator | Maintenance timing and type (patch or resurface), reroute or hold advice, overload enforcement alerts, pothole dispatch with coordinates |

Trucks appear in the dashboard as traffic and as mobile roughness probes. The project does not model fleets or
vehicle health.

## Architecture

```
 simulation: World (hidden truth) ┐
 hybrid:     World + recorded     ├─> normalized contracts ─> TwinEngine ─> snapshot ─> REST / WebSocket ─> 3D dashboard
             real weather         │   (routetwin/contracts.py)    │  EKF per segment      
 live:       signed POST /ingest  ┘                               │  persistence filter (potholes)
                                                                  │  ISA-18.2 alarm manager
                                                                  └─ decisions: reroute advice, maintenance queue
```

The twin engine consumes only contract messages (`segment_obs`, `probe_obs`, `vehicle_pos`, `weather_obs`,
`incident`, `maintenance`). Changing the data mode never touches twin logic.

**How the twin stays in sync.** Per segment, an extended Kalman filter holds damage `D` and a load-response
multiplier `theta`. Traffic measurements drive the *predict* step (`D += theta * u`, with `u = ESAL x temperature
factor x moisture factor / design ESAL`). Roughness observations drive the *update* step. Because `D` drifts at a
rate set by `theta`, the filter also learns each segment's structural weakness over weeks (convergence is slow: in
30 simulated days the condition index is within about 0.3 points of truth, while `theta` has not fully converged).
Potholes use a persistence filter: a real pothole is hit on most passes, spurious impacts are not.

## Data modes

| Mode | Source | Reproducible | Needs |
|---|---|---|---|
| `simulation` | Seeded simulator | Yes | Nothing |
| `hybrid` | Simulated traffic and pavement driven by a **recorded real hourly weather series** (Open-Meteo) | Yes, after recording | Run `make record-weather` once with internet. Refuses to start otherwise |
| `live` | Devices post HMAC-signed batches to `/api/ingest` | No | `ROUTETWIN_OPERATOR_TOKEN`, `ROUTETWIN_INGEST_KEY` |

`scripts/live_client_example.py` shows the signing. Other public sources (FRSC observatory, FERMA GIS, TomTom,
NiMet) were not found usable for this corridor, so no adapters are claimed for them; the contract is the integration
point if access is obtained.

## Repository layout

```
routetwin/    contracts, corridor, pavement, iri, estimator, twin, alarms, decision, simulator, weather,
              runtime, security, api, geometry_osm
web/          dashboard (Three.js vendored in web/vendor, no build step, no CDN)
scripts/      compare_policies, record_weather, fetch_osm_corridor, live_client_example
data/         corridor definition; simulated/ and field/ are kept separate
docs/         standards_mapping.md, results.md
tests/        46 tests
```

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/state?truth=true` | Twin snapshot (truth only in modes with a simulated world) |
| `GET /api/config`, `GET /api/segment/{id}/history` | Corridor and condition history |
| `POST /api/control`, `/api/scenario`, `/api/workorder`, `/api/alarms/{id}/ack`, `/api/alarms/ack_all` | Operator actions (token required outside simulation mode) |
| `POST /api/ingest` | Signed telemetry, live mode only |
| `WS /ws` | Snapshot stream, twice a second |

## Known limitations

* All constants (capacities, design ESAL, damage and speed coefficients, hazard rates, bypass options) are
  illustrative. The corridor waypoints are approximate; `make osm` can rebuild them from OpenStreetMap.
* The IRI implementation omits the standard 250 mm moving-average pre-filter.
* Open-Meteo and Overpass scripts were written to the public API descriptions but were not run against the live
  services during development.
* The dashboard was developed without an automated browser test; the JavaScript was syntax-checked and the
  served API tested, but visual behaviour should be checked in a browser before a demo.
* Simulation uses accelerated, seeded scenarios; see `docs/results.md` for how results should be quoted.
