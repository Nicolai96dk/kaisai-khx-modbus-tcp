![Kaisai KHX Modbus TCP](assets/banner.png)

# Kaisai KHX Modbus TCP

[![Validate](https://github.com/Nicolai96dk/kaisai-khx-modbus-tcp/actions/workflows/validate.yml/badge.svg)](https://github.com/Nicolai96dk/kaisai-khx-modbus-tcp/actions/workflows/validate.yml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories/)
[![GitHub release](https://img.shields.io/github/v/release/Nicolai96dk/kaisai-khx-modbus-tcp)](https://github.com/Nicolai96dk/kaisai-khx-modbus-tcp/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A UI-configured Home Assistant custom integration for KAISAI KHX R290 heat pumps.

## Supported model profiles

The integration provides immutable built-in profiles for:

| Profile | Supply | Fans | Max input | Reference water flow | Status |
|---|---:|---:|---:|---:|---|
| KAISAI KHX-09PY1 | 220–240 V / 50 Hz | 1 | 3.0 kW | 1.0 m³/h | Development reference |
| KAISAI KHX-14PY3 | 380–415 V / 3N~ / 50 Hz | 1 | 5.3 kW | 1.7 m³/h | Documentation-derived |
| KAISAI KHX-16PY3 | 380–415 V / 3N~ / 50 Hz | 2 | 9.0 kW | 2.9 m³/h | Documentation-derived |

All models use one common manual-derived register map plus separate capability metadata. KHX-09PY1 and KHX-14PY3 do not create Fan 2 entities. KHX-16PY3 does. The documented physical fan ranges are retained as profile metadata, but Modbus fan registers remain unitless raw values because the protocol does not identify them as RPM.

Only KHX-09PY1 is the development reference. The KHX-14PY3 and KHX-16PY3 profiles come from the shared technical manual and need real-device verification. Firmware may differ.

## Architecture

The integration currently owns one Modbus TCP connection per configured heat pump through Home Assistant's `modbus-connection` Python package and its pymodbus backend. It does not depend on a nonexistent Home Assistant `modbus_connection` integration. Device logic accepts only the backend-neutral `ModbusUnit` protocol, keeping transport code isolated for a future shared Core connection API.

## Installation and setup

### HACS installation

1. Open HACS in Home Assistant.
2. Select **Integrations**.
3. Open the three-dot menu and choose **Custom repositories**.
4. Add `https://github.com/Nicolai96dk/kaisai-khx-modbus-tcp` with category **Integration**.
5. Search for **Kaisai KHX Modbus TCP**, install it, and restart Home Assistant.
6. Open **Settings → Devices & services → Add integration → Kaisai KHX Modbus TCP**.

For a manual installation, copy `custom_components/kaisai_khx` into Home Assistant's `custom_components` directory and restart.

Setup asks for the connection, one of the three exact models, and the features to enable. It then offers only two advanced choices: polling interval and the climate entity's current-temperature source. The source can be water inlet, water outlet (default), or DHW tank temperature when DHW is enabled.

The feature page supports Heating, Cooling, optional DHW, monitoring-only operation, a separate power switch, actual power-state readback, fault monitoring, individual fault sensors, performance diagnostics, hardware input/output diagnostics, the read-only maximum outlet-temperature diagnostic, connection diagnostics, and **Debug diagnostics**. Debug diagnostics enables every applicable diagnostic entity for the selected model without expanding write access. Fan 2 remains model-controlled.

## Entities and fault support

The integration provides climate control (`off`, `heat`, `cool`), inlet/outlet/ambient temperatures, compressor frequency, operating status, model-aware fan diagnostics, and optional DHW entities.

Fault registers 2081, 2082, 2083, 2085–2090 are decoded into:

- an enabled **Fault** problem binary sensor;
- an enabled **Active fault** diagnostic sensor with controller codes where the manual supports an exact mapping, descriptions, categories, source registers/bits, and raw words;
- individual documented fault binary sensors, disabled by default;
- raw register words in downloaded diagnostics, without creating raw state entities.

Immediate/current protections and three-or-more-times repeated/latched protections are identified separately. Single-phase-only faults are omitted for three-phase profiles, and Fan 2 faults are omitted for one-fan profiles. If an optional fault register is unavailable, normal climate polling continues.

The published Modbus table does not document the controller's historical fault-log records or occurrence timestamps. v1 therefore reports current bitfields and repeated/latched indicators only; it does not fabricate fault history.

Output register 2019 and active-low input register 2034 are represented by profile-defined diagnostic binary sensors. Register 2013 is decoded from real-device behaviour at 0.1 °C resolution (`206` becomes `20.6 °C`); register 2014 uses the documented `TEMP` decoder. Register 1238 is a read-only diagnostic. These extended diagnostics are enabled automatically by Debug diagnostics.

## Write safety

Profiles never authorize Modbus writes. The integration has a hard-coded semantic allowlist containing only:

- power;
- operating mode;
- heating target temperature;
- cooling target temperature;
- DHW target temperature.

Every permitted value is checked against the active built-in profile and hard integration-level sanity limits. Factory, installer, compressor, EEV, defrost, fan, electrical, phase, protection, fault, status, and arbitrary registers remain read-only even if a manual labels them read/write. Register 1238 is never exposed as a writable Number. No arbitrary-register editor, test, or write service is exposed in the UI.

Power commands are sent to 1011. When optional actual-state register 2011 is readable, it is used for confirmation; otherwise confirmation safely falls back to 1011. A readable mismatch is reported as a failed write.

## KAISAI data types

The internal decoder implements `TEMP`, `DIGI1`, `DIGI2`, `DIGI3`, `DIGI4`, `DIGI5`, `DIGI6`, and `DIGI9` as first-class types. `TEMP` is signed 16-bit at 0.1 °C resolution, and raw value 32767 is invalid.

## Validation and troubleshooting

The options flow is intentionally limited to polling interval and current-temperature source.

- Keep Modbus TCP on a trusted network; do not expose port 502 publicly.
- Confirm whether another client is monopolizing a single-connection gateway.
- This integration sends configured addresses unchanged; verify whether external documents/tools display addresses as zero- or one-based.
- Download diagnostics from the integration entry. The host address is deliberately excluded. Diagnostics include profile/capability metadata, connection health, decoded data, active and repeated faults, raw fault words, and unavailable optional registers.
- The manual calls several measured/status registers function 16 or “write.” This integration conservatively treats them as read-only unless their semantic function is in the allowlist above.

## Development

Run:

```text
python -m pytest
ruff check .
python -m compileall custom_components
```

CI also runs HACS and hassfest validation.

## License

MIT
