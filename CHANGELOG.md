# Changelog

All notable changes to this project are documented here.

## 0.7.5 — 2026-11-25

- Add estimated heat output in kW with one decimal place by default.
- Show Heat output alongside COP and SCOP when an electrical power sensor and flow rate are configured.
- Keep standard integration setup and polling available when efficiency options are incomplete.

## 0.7.4 — 2026-11-21

- Use a single numeric COP sensor, retaining its existing entity ID and history.
- Mark COP unavailable when there is no valid reading and retire the text-only COP entity.

## 0.7.3 — 2026-11-21

- Show live COP or its operating status in one COP row, with the last valid reading and timestamp in the details.
- Keep the existing numeric COP entity and history under Diagnostics as Live COP.
- Report SCOP to one decimal place on the device page.

## 0.7.2 — 2026-11-21

- Prefill the efficiency setup flow with the selected model’s reference flow rate.
- Keep any saved flow rate when reopening Configure.
- Show the reason when live COP has no numeric reading, including when water flow has stopped.
- Display COP and SCOP to one decimal place by default.
- Use the native climate temperature properties on Home Assistant 2026.11 and newer.

## 0.7.1 — 2026-11-21

- Added optional estimated COP and rolling seasonal performance factor sensors.
- Added editable electrical power sensor and circulating water flow settings.
- Used the KHX water-flow switch and circulation pump output to gate the heat estimate.
- Allowed compatible Modbus connection library versions for newer Home Assistant releases.

## 0.6.0 — 2026-09-08

- Added an Adaptive learning heat-curve mode that passively learns bounded corrections on top of Predictive + indoor compensation.
- Added automatic Observing, Blending, Active, and Paused learning phases with confidence reporting and detailed fallback status.
- Limited learned corrections to `±3 °C` and hourly changes to `±0.25 °C`, while retaining all profile and integration heating-target safety limits.
- Added diagnostic entities for learned correction, learning confidence, and learning phase, plus a local reset button.
- Persisted only minimal delayed-response learning data per heat pump; no indoor-temperature history is stored.

## 0.5.0 — 2026-09-07

- Replaced the heat-curve enable switch with exclusive Manual, Ambient heat curve, Predictive heat curve, and Predictive + indoor compensation modes.
- Added a configurable 1–12 hour prediction horizon using Home Assistant hourly weather forecasts.
- Added optional indoor-temperature compensation with a configurable room target and a safety-bounded correction.
- Added explicit forecast and sensor fallback behavior with a detailed heat-curve status sensor.
- Added diagnostic sensors for the calculated target, effective ambient temperature, forecast temperature, and indoor correction.
- Migrated existing enabled heat-curve configurations to Ambient heat curve without expanding the semantic Modbus write allowlist.

## 0.1.0 — 2026-08-13

- Initial public HACS-compatible release.
- Added immutable KHX-09PY1, KHX-14PY3, KHX-16PY3, and generic KHX R290 profiles.
- Added guided custom profiles with register and capability configuration.
- Added model-aware Modbus fault decoding for registers 2081–2090.
- Added aggregate fault entities, diagnostics, and optional individual fault entities.
- Added hard-coded semantic write safety and verified operational writes.
- Added current Home Assistant config, reconfigure, coordinator, diagnostics, and translation architecture.
