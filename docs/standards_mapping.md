# Standards mapped to design choices and verification evidence

Listing standards is not enough; each row links a requirement to a design choice, to where it lives in the
repository, and to evidence you can run. "Evidence" column entries are test names (`pytest -q`) unless stated.

**Scope note.** Clause numbers and editions below must be confirmed against the copies you hold before the
proposal cites them. Where a standard was written for another domain (machines, manufacturing), the mapping is by
analogy and says so. Nothing here claims certification or compliance.

| Standard | Requirement area | Design choice | Where | Evidence |
|---|---|---|---|---|
| ISA-18.2 | Alarm lifecycle and philosophy | Every alarm has priority, setpoint, deadband, on-delay, consequence and operator action; states active-unack, active-ack, return-to-normal-unack; only action-requiring conditions alarm (amber congestion is display-only) | `routetwin/alarms.py`, `DEFS` in `routetwin/twin.py` | `test_alarms.py::test_on_delay_blocks_single_spike`, `::test_deadband_prevents_chatter_and_lifecycle`, `::test_return_to_normal_unacknowledged_then_ack` |
| ISA-18.2 | Rationalisation, suppression by design | Child alarms suppressed while a parent holds (closure suppresses congestion on and near the blocked segment; critical condition suppresses maintenance-due; stale data suppresses traffic and overload alarms) | `TwinEngine.evaluate` | `::test_suppression_removes_child_alarm`, `test_system.py::test_closure_raises_alarm_and_advisory_and_return_to_normal` |
| ISA-18.2 | Performance monitoring | KPIs: raised per 10 min, flood events (more than 10 in 10 min), standing alarms, chattering tags | `AlarmManager.kpis` | `::test_flood_kpi` |
| ISA-101 | HMI philosophy | Neutral graphite display; colour reserved for abnormal states; consistent navigation (segment list, 3D view, alarm/advice/maintenance/segment tabs); keyboard focus visible | `web/style.css`, `web/app.js` | Inspection (no automated test) |
| ISA/IEC 62443 (3-3) | Identification and authentication (SR 1.1, 1.2) | Telemetry devices authenticate with a shared-key HMAC; operators with a token; hybrid/live refuse to start without credentials | `routetwin/security.py`, `Runtime.__init__`, `api.operator` | `test_system.py::test_non_simulation_modes_refuse_to_start_unsecured`, `test_api.py::test_live_mode_signed_ingestion_and_operator_auth` |
| ISA/IEC 62443 (3-3) | Communication integrity, replay (SR 3.1) | Signature covers timestamp and body; freshness window; signature cache | `IngestVerifier` | `test_contracts_security.py::test_signature_*` |
| ISA/IEC 62443 (3-3) | Input validation (SR 3.5) | Strict typed contracts with range checks; batch size cap | `routetwin/contracts.py` | `test_contracts_security.py::test_invalid_values_rejected` |
| ISA/IEC 62443 (3-3) | Auditable events (SR 2.8) | Append-only JSONL log of control, scenario, work-order, acknowledgement, auth failures, rejected ingest | `AuditLog` | `test_api.py::test_live_mode_signed_ingestion_and_operator_auth` (log contents) |
| ISA-95 | Enterprise-control integration | A work order completion is exchanged as a typed `MaintenanceEvent`; the maintenance queue is the interface to a maintenance or asset system. This is the information model idea only, not a B2MML implementation | `contracts.MaintenanceEvent`, `decision.maintenance_queue` | `test_system.py::test_maintenance_resets_twin_and_world` |
| ISO 13374 (by analogy) | Condition-monitoring data flow | Data acquisition (contracts), data manipulation (EWMA, persistence filter), state detection (alarm logic), health assessment (EKF condition index), prognostics (remaining life), advisory generation (maintenance and reroute advice) | `twin.py`, `estimator.py`, `decision.py` | `test_estimator.py`, `test_system.py` |
| ISO 23247 (by analogy) | Digital twin framework | Observable element (road segment with stations), data collection (contracts and adapters), twin core (engine), user entity (dashboard and API) | architecture in README | README diagram |
| ISO 8608 | Road profile roughness classes | Synthetic profiles of known class used to verify the IRI computation | `routetwin/iri.py` | `test_pavement_iri.py::test_iri_orders_iso8608_classes`, `::test_iri_is_linear_in_amplitude` |
| ASTM E1926 / World Bank IRI | Roughness index | Golden-car IRI at 80 km/h (the 250 mm moving-average pre-filter is not implemented; stated limitation) | `routetwin/iri.py` | `::test_iri_flat_profile_is_zero` |
| AASHTO 1993 pavement guide (method) | Load equivalency | Fourth-power approximation per axle group for equivalent standard axle loads | `routetwin/pavement.py` | `::test_fourth_power_law`, `::test_overloading_is_disproportionately_damaging` |
| Nigeria Data Protection Act 2023 | Personal data | The twin needs no driver identity: vehicle identifiers are opaque and optional, location data stays on the corridor, retention is configurable (not yet enforced in code) | contracts | Design statement only |

## Simulated versus field evidence

| Claim | Basis |
|---|---|
| The IRI computation is implemented correctly | Verified against synthetic ISO 8608 profiles (simulated, with analytic properties) |
| The estimator recovers hidden pavement state | Verified in simulation against hidden ground truth (`test_twin_tracks_hidden_condition_truth`) |
| Model parameters match Nigerian pavements and traffic | **Not demonstrated.** All constants are illustrative placeholders |
| Real-weather response (hybrid mode) | Only after `scripts/record_weather.py` has been run with internet access |
| Field sensor performance | **No field data.** Live mode is implemented and tested with synthetic signed messages only |
