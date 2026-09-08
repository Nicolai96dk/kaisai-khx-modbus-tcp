# Changelog

All notable changes to this project are documented here.

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
