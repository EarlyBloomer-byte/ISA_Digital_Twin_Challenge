# Claims in the proposal and where they live in the code

Use this to check that what the proposal says is what the repository does. "Test" means a test in `tests/`; "Script"
means something you run to reproduce a number. Anything marked *inspection* has no automated test.

| Claim in the proposal | Code | Evidence |
|---|---|---|
| ESAL = sum over steer / drive-tandem / trailer-tandem of (P/Pref)^4; shares 10/45/45 %; Pref 80 kN single, 148 kN tandem | `routetwin/pavement.py` | `test_pavement_iri.py::test_fourth_power_law`, `::test_overloading_is_disproportionately_damaging` |
| Temperature factor doubles per +15 C above 30 C, clipped 0.5 to 3; moisture factor 1 + w | `pavement.py` | `::test_temperature_and_moisture_raise_damage_rate` |
| Wetness state rises with rain, decays with a 24 h time constant | `simulator.py` (truth), `twin.py::_weather_obs` | inspection |
| D(k+1) = D(k) + theta * u, u = ESAL f_T f_W / N_design | `simulator.py`, `twin.py::_segment_obs` | `test_system.py::test_twin_tracks_hidden_condition_truth` |
| CI = 100 (1 - D^1.3); IRI = 1.5 + 7 D^1.3 | `pavement.py` | `::test_condition_and_iri_are_monotone`, `::test_damage_ci_roundtrip` |
| Golden-car IRI at 80 km/h; simulated IRI by ISO 8608 class A 2.1, B 4.3, C 8.6, D 17.2 m/km | `routetwin/iri.py` | `::test_iri_flat_profile_is_zero`, `::test_iri_is_linear_in_amplitude`, `::test_iri_orders_iso8608_classes` (class values are from a run, not asserted) |
| Extended Kalman filter on (D, theta); Q = diag((0.05 theta u)^2, 3.5e-7); noise 0.6 m/km; 4-sigma rejection, accepted after 5 in a row; Joseph form | `routetwin/estimator.py` | `test_estimator.py` |
| Remaining life to CI 45 at the smoothed damage rate | `twin.py::_rul` | inspection |
| Pothole filter: merge within 40 m, confirm at 3 hits and 35 % of passes, discard at 12 passes under 20 % | `twin.py::_probe_obs`, `::evaluate` | `test_system.py::test_twin_finds_the_true_potholes_without_false_ones` |
| Cell-transmission traffic, 1800 veh/h/lane, 110 veh/km/lane jam density; pavement lowers free-flow speed | `simulator.py` | `test_system.py` scenario tests |
| Speed smoothing (alpha 0.4); slow below 30 km/h; severe below 10 km/h or closed | `twin.py` | `test_system.py::test_recurrent_bottleneck_slows_traffic...`, `::test_incidents_drive_segments_red...` |
| Maintenance queue; patch cost 1, resurface 12 | `routetwin/decision.py` | `::test_maintenance_resets_twin_and_world` |
| Per-segment reroute or hold advice | `decision.py::traffic_advisories` | `::test_closure_raises_alarm_and_advisory_and_return_to_normal` |
| Fresh random run per start; worn sections start with potholes; up to three scenarios, no repeats; Stop and restart; ten speeds | `simulator.py` (`add_scenario`, `initial_potholes`), `runtime.py`, `api.py`, `web/app.js` | `test_runs.py`; dialog, speeds and layout: inspection |
| Overload alert when ESAL per truck stays above 2.6 | `twin.py` (`TwinConfig`) | `::test_overload_raises_alarm_and_accelerates_damage` |
| Six typed message contracts, validated on arrival | `routetwin/contracts.py` | `test_contracts_security.py` |
| HMAC-signed ingestion, replay protection, audit log, refusal to start unsecured outside simulation, operator tokens | `security.py`, `runtime.py`, `api.py` | `test_contracts_security.py`, `test_api.py`, `test_system.py::test_non_simulation_modes_refuse_to_start_unsecured` |
| ISA-18.2 style alarms: priority, setpoint, deadband, on-delay, acknowledgement lifecycle, suppression, flood KPI | `alarms.py`, alarm definitions in `twin.py` | `test_alarms.py` |
| Standing and chattering alarm counts, and a consequence text per alarm | `alarms.py` | `test_alarms.py` (flood KPI); the consequence text is not shown on the dashboard |
| 61 automated tests | `tests/` | `make test` |
| Hybrid mode needs a recorded real weather series; not yet run live | `weather.py`, `scripts/record_weather.py` | `test_system.py::test_hybrid_requires_recorded_weather_and_uses_it` (synthetic series only) |
| CI error 0.26 points after 30 days (seed 42, demonstration storyline); potholes match truth | `scripts/headline_accuracy.py` | Script |
| CI error 0.34 to 0.40 points in the 180-day maintenance runs; policy table | `scripts/compare_policies.py` | `data/simulated/policy_comparison.csv`, `docs/results.md` |
| Matched: CI error 0.50, NIS 1.13, truth within 2 SD on 64 %; mismatched: bias +12.3, NIS 1.13 | `scripts/validate_estimator.py` | `data/simulated/estimator_validation.csv`, `docs/validation.md` |
| Pilot cost build-up: local works N26.7 million per station (USD 19.6 thousand at N1,365/USD), equipment assumed, total about USD 189,500 | `scripts/cost_estimate.py` | Script; `docs/costing.md`. Rates from the Buildocrat rate book and BuildMNO rate card; equipment prices are assumptions |

Not implemented, and stated as such in the proposal: probe-vehicle speed and load correction of roughness, known-feature
map for potholes, station sharing across segments, reclassifying condition alarms as advisories, roles/zones/key
management/encryption, retention policy enforcement.
