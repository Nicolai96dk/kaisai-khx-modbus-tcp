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
| KAISAI KHX R290 (Generic) | Unknown | Optional | Unknown | Unknown | Fallback |

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

The first screen asks only for host, port (default 502), Unit ID (default 1), and device name. Setup performs a read-only connection check. The second screen selects an exact model, the generic profile, or **Custom**.

Custom setup first clones a built-in profile and then provides grouped pages for:

- descriptive device capabilities, including phase, fan count, Fan 2, DHW, and fault monitoring;
- polling, timeout, and gateway message pacing;
- guided address mapping for all known registers;
- KAISAI data type, scale multiplier, offset, invalid values, range, and enum decoding;
- climate source and target ranges;
- review before saving.

Any change creates an entry-local Custom profile. Built-in profiles remain immutable.

## Entities and fault support

The integration provides climate control (`off`, `heat`, `cool`), inlet/outlet/ambient temperatures, compressor frequency, operating status, model-aware fan diagnostics, and optional DHW entities.

Fault registers 2081, 2082, 2083, 2085–2090 are decoded into:

- an enabled **Fault** problem binary sensor;
- an enabled **Active fault** diagnostic sensor with controller codes where the manual supports an exact mapping, descriptions, categories, source registers/bits, and raw words;
- individual documented fault binary sensors, disabled by default;
- raw register words in downloaded diagnostics, without creating raw state entities.

Immediate/current protections and three-or-more-times repeated/latched protections are identified separately. Single-phase-only faults are omitted for three-phase profiles, and Fan 2 faults are omitted for one-fan profiles. If an optional fault register is unavailable, normal climate polling continues.

The published Modbus table does not document the controller's historical fault-log records or occurrence timestamps. v1 therefore reports current bitfields and repeated/latched indicators only; it does not fabricate fault history.

Output register 2019 and active-low input register 2034 are represented by profile-defined diagnostic binary sensors disabled by default. Register 2013 is decoded as unitless `DIGI1`; register 2014 is decoded as `TEMP`. Register 1238 is a read-only, disabled-by-default diagnostic.

## Write safety

Profiles never authorize Modbus writes. The integration has a hard-coded semantic allowlist containing only:

- power;
- operating mode;
- heating target temperature;
- cooling target temperature;
- DHW target temperature.

A custom profile may remap the address and decoding for one of those known controls, but it cannot make another register writable. The guided editor has no writable toggle, JSON attempts to change authorization are rejected, the register test is read-only, and no arbitrary-register write service exists.

Every permitted value is checked against the active profile and hard integration-level sanity limits. Factory, installer, compressor, EEV, defrost, fan, electrical, phase, protection, fault, status, and arbitrary registers remain read-only even if a manual labels them read/write. Register 1238 is never exposed as a writable Number.

Power commands are sent to 1011. When optional actual-state register 2011 is readable, it is used for confirmation; otherwise confirmation safely falls back to 1011. A readable mismatch is reported as a failed write.

## KAISAI data types

The profile decoder implements `TEMP`, `DIGI1`, `DIGI2`, `DIGI3`, `DIGI4`, `DIGI5`, `DIGI6`, and `DIGI9` as first-class types. `TEMP` is signed 16-bit at 0.1 °C resolution, and raw value 32767 is invalid. Custom scaling is an additional multiplier on the documented native resolution.

## Validation and troubleshooting

The options flow includes a read-only register test with raw decimal/hex output and bitfield preview, plus profile validation that distinguishes required registers, available/unavailable optional registers, and model-inapplicable features.

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
