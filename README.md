# RouteTwin NG

A digital twin of a **smart road**: the Lagos-Ibadan expressway modelled as thirteen instrumented segments whose
pavement condition, traffic state and maintenance needs are estimated continuously from sensor data and acted on
through alarms, reroute advice and a maintenance queue. Built for the ISA Nigeria Next-Gen Automation Challenge.

> Nothing here is field evidence. Sensors, traffic and pavement truth come from a simulator and every model constant is
> an illustrative placeholder. What is verified is that the twin implements its models correctly (see `tests/`,
> `docs/claims.md` and `docs/standards_mapping.md`).

## Run it locally

```bash
python3 -m venv .venv && source .venv/bin/activate      # optional
pip install -r requirements.txt
python -m routetwin                                      # then open http://127.0.0.1:8000
```

`make run` does the same. `python -m routetwin --demo --seed 42` skips the start dialog and begins the seeded,
reproducible run with the scripted storyline.

On first load a dialog asks which scenarios to run: up to three together (heavy rain, overloaded trucks, traffic surge,
road closure, accident, sensor outage), or none. **Pause** freezes the run. **Stop** discards it (after a confirmation)
and returns to the dialog for a fresh one. The speed menu has ten rates, from 10 simulated minutes per second to 2 days
per second. Every run starts from a new random road, so the worn sections and potholes differ each time; the run's seed is
shown under the header, and typing it into the dialog repeats that run. Scenarios can also be added during a run while
fewer than three are active.

## What is being twinned

| Physical asset | Sensors (simulated) | Model | Decisions supported |
|---|---|---|---|
| A pavement segment (4.9 to 14.5 km, 2 or 3 lanes per direction) | Roadside station per segment: counts, mean speed, weigh-in-motion ESAL per truck, pavement temperature; roughness readings from passing instrumented trucks | Load-driven damage (fourth-power ESAL law with temperature and moisture factors), condition index, IRI, remaining life | Maintenance timing and type, reroute or hold advice, overload alerts, pothole dispatch with coordinates |

Trucks appear as traffic and as mobile roughness probes. The project does not model fleets or vehicle health. Flow
figures are hourly rates per direction. The demand profile peaks near 3,500 veh/h per direction and implies roughly
75,000 vehicles a day across both directions, which is an uncalibrated assumption.

## Architecture and data modes

```
 simulation: World (hidden truth) ┐
 hybrid:     World + recorded     ├─> normalized contracts ─> TwinEngine ─> snapshot ─> REST / WebSocket ─> 3D dashboard
             real weather         │   (routetwin/contracts.py)    │  Kalman filter per segment
 live:       signed POST /ingest  ┘                               │  persistence filter (potholes)
                                                                  │  ISA-18.2 alarm manager
                                                                  └─ decisions: reroute advice, maintenance queue
```

| Mode | Source | Needs |
|---|---|---|
| `simulation` (default) | Seeded or random simulator | Nothing |
| `hybrid` | Simulated traffic and pavement driven by a recorded real hourly weather series | `make record-weather` once, with internet |
| `live` | Devices post HMAC-signed batches to `/api/ingest` | `ROUTETWIN_OPERATOR_TOKEN`, `ROUTETWIN_INGEST_KEY` |

The twin engine only sees six typed message contracts, so changing the data mode never touches twin logic. Hybrid and live
modes require an operator token (the server refuses to start without one); see `scripts/live_client_example.py`.

## Layout

```
routetwin/    contracts, corridor, pavement, iri, estimator, twin, alarms, decision, simulator, weather, runtime, security, api
web/          dashboard (Three.js is included, no build step, no network access at run time)
scripts/      compare_policies, validate_estimator, headline_accuracy, record_weather, fetch_osm_corridor, live_client_example
data/         corridor definition; simulated/ and field/ outputs, kept separate
docs/         claims.md, standards_mapping.md, results.md, validation.md, proposal/ (LaTeX source and PDF)
tests/        61 tests (make test)
```

## API

`GET /api/state`, `/api/config`, `/api/segment/{id}/history`; operator actions `POST /api/run/start`, `/api/run/stop`,
`/api/control`, `/api/scenario`, `/api/workorder`, `/api/alarms/{id}/ack`; signed `POST /api/ingest` (live only);
`WS /ws` (four updates a second).

## Studies behind the proposal

`make compare` (maintenance policies), `make validate` (filter consistency and model mismatch), `make headline` (30-day
accuracy). Results are written to `data/simulated/` and summarised in `docs/results.md` and `docs/validation.md`. They use
the seeded default simulator, not the randomised dashboard runs.

## Known limitations

* All constants are illustrative placeholders; corridor waypoints are approximate (`make osm` rebuilds them from OpenStreetMap).
* The IRI implementation omits the 250 mm moving-average pre-filter.
* The weather-recording and OpenStreetMap scripts were written to the public API descriptions but not run live.
