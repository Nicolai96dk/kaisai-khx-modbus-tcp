"""Distribution metadata tests."""

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_manifest_uses_owned_modbus_connection_transport() -> None:
    manifest = json.loads((ROOT / "custom_components/kaisai_khx/manifest.json").read_text())
    assert manifest["domain"] == "kaisai_khx"
    assert "modbus_connection" not in manifest.get("dependencies", [])
    assert "modbus-connection[pymodbus]==3.8.1" in manifest["requirements"]


def test_hacs_and_translation_metadata() -> None:
    hacs = json.loads((ROOT / "hacs.json").read_text())
    strings = json.loads((ROOT / "custom_components/kaisai_khx/strings.json").read_text())
    translation = json.loads((ROOT / "custom_components/kaisai_khx/translations/en.json").read_text())
    assert hacs["homeassistant"] == "2026.8.0"
    assert strings["title"] == translation["title"]
    assert strings == translation
    assert "reconfigure" in strings["config"]["step"]
    assert "features" in strings["config"]["step"]
    assert "advanced" in strings["config"]["step"]
    assert set(strings["options"]["step"]["init"]["data"]) == {
        "heating_enabled",
        "cooling_enabled",
        "dhw_enabled",
        "control_enabled",
        "power_switch_enabled",
        "power_state_readback_enabled",
        "enable_fault_monitoring",
        "individual_fault_sensors_enabled",
        "performance_diagnostics_enabled",
        "io_diagnostics_enabled",
        "max_outlet_diagnostic_enabled",
        "connection_diagnostics_enabled",
        "debug_diagnostics_enabled",
    }
    assert set(strings["options"]["step"]["advanced"]["data"]) == {
        "scan_interval",
        "current_temperature_register",
    }
    assert "active_fault" in strings["entity"]["sensor"]
    assert "fault" in strings["entity"]["binary_sensor"]
    assert (ROOT / "custom_components/kaisai_khx/brand/icon.png").is_file()
    assert hacs["zip_release"] is True
    assert hacs["filename"] == "kaisai_khx.zip"


def test_entity_enablement_matches_safety_requirements() -> None:
    integration = ROOT / "custom_components/kaisai_khx"
    sensor_source = (integration / "sensor.py").read_text()
    binary_sensor_source = (integration / "binary_sensor.py").read_text()
    assert 'translation_key = "active_fault"' in sensor_source
    assert 'translation_key = "fault"' in binary_sensor_source
    assert "entity_registry_enabled_default=False" in sensor_source
    assert "entity_registry_enabled_default = False" in binary_sensor_source


def test_setup_exposes_only_exact_models_and_selected_features() -> None:
    source = (ROOT / "custom_components/kaisai_khx/config_flow.py").read_text()
    assert "async_step_profile" in source
    assert "async_step_features" in source
    assert "async_step_advanced" in source
    assert "GENERIC_PROFILE_ID" not in source
    assert "CUSTOM_PROFILE" not in source
    assert "KHX_09_PROFILE_ID" in source
    assert "KHX_14_PROFILE_ID" in source
    assert "KHX_16_PROFILE_ID" in source
    for feature in (
        "CONF_HEATING",
        "CONF_COOLING",
        "CONF_DHW",
        "CONF_CONTROL",
        "CONF_FAULT_MONITORING",
        "CONF_DEBUG_DIAGNOSTICS",
    ):
        assert feature in source
    assert "include_profile" not in source
    assert "data_schema=connection_schema(defaults)" in source
    assert "data[CONF_PROFILE] = entry.data.get" in source


def test_post_setup_options_repeat_features_then_advanced() -> None:
    source = (ROOT / "custom_components/kaisai_khx/config_flow.py").read_text()
    readme = (ROOT / "README.md").read_text()

    assert "class KaisaiOptionsFlow(OptionsFlowWithReload)" in source
    assert "data_schema=features_schema(dict(self.config_entry.options))" in source
    assert "return await self.async_step_advanced()" in source
    assert "data_schema=advanced_schema(self._updated_options" in source
    assert "features such as DHW" in readme
    assert "selected model is intentionally locked after setup" in readme


def test_number_selector_never_receives_a_null_step() -> None:
    """A null selector step prevents Home Assistant from loading the first form."""
    source = (ROOT / "custom_components/kaisai_khx/config_flow.py").read_text()
    assert "step=step" not in source
    assert 'if step is not None:' in source
    assert 'config["step"] = step' in source


def test_release_versions_match() -> None:
    manifest = json.loads((ROOT / "custom_components/kaisai_khx/manifest.json").read_text())
    const_source = (ROOT / "custom_components/kaisai_khx/const.py").read_text()
    release_workflow = (ROOT / ".github/workflows/release.yml").read_text()
    assert manifest["version"] == "0.3.0"
    assert 'VERSION = "0.3.0"' in const_source
    assert '--title "${GITHUB_REF_NAME}"' in release_workflow


def test_rs485_gateway_requirements_are_documented() -> None:
    readme = (ROOT / "README.md").read_text()
    strings = json.loads((ROOT / "custom_components/kaisai_khx/strings.json").read_text())
    first_step = strings["config"]["step"]["user"]

    assert "do **not** have Ethernet or Modbus TCP built in" in readme
    assert "Modbus TCP to RTU" in readme
    assert "RS485 TO POE ETH (B)" in readme
    assert "| Serial | Baud Rate | 9600 |" in readme
    assert first_step["data"]["host"] == "Gateway host/IP"
    assert "no built-in Modbus TCP" in first_step["description"]


def test_no_generic_write_surface_exists() -> None:
    integration = ROOT / "custom_components/kaisai_khx"
    source = "\n".join(path.read_text() for path in integration.glob("*.py"))
    assert "async_register_service" not in source
    assert "write_register_service" not in source
    assert "SEMANTIC_WRITE_ALLOWLIST" in (integration / "profile.py").read_text()
