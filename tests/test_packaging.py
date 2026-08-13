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
    assert "advanced_setup" in strings["config"]["step"]
    assert "advanced_register_details" in strings["config"]["step"]
    assert "test_register" in strings["options"]["step"]
    assert "writable" not in strings["config"]["step"]["advanced_register_details"]["data"]
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


def test_setup_exposes_guided_custom_profile() -> None:
    source = (ROOT / "custom_components/kaisai_khx/config_flow.py").read_text()
    assert "guided register and capability setup" in source
    assert "async_step_profile" in source
    assert "async_step_custom_base" in source
    assert "async_step_advanced_capabilities" in source
    assert "async_step_advanced_communication" in source
    assert "async_step_advanced_addresses" in source
    assert "async_step_advanced_register_details" in source
    assert "async_step_advanced_climate" in source


def test_no_generic_write_surface_exists() -> None:
    integration = ROOT / "custom_components/kaisai_khx"
    source = "\n".join(path.read_text() for path in integration.glob("*.py"))
    assert "async_register_service" not in source
    assert "write_register_service" not in source
    assert "SEMANTIC_WRITE_ALLOWLIST" in (integration / "profile.py").read_text()
