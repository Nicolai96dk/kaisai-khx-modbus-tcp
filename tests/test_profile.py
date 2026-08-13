"""Profile decoding tests."""

import json

import pytest

from custom_components.kaisai_khx.models import (
    KHX_09_PROFILE_ID,
    KHX_14_PROFILE_ID,
    KHX_16_PROFILE_ID,
    ElectricalPhase,
)
from custom_components.kaisai_khx.profile import (
    BUILTIN_PROFILE,
    BUILTIN_PROFILES,
    DataType,
    RegisterDefinition,
    profile_for_capabilities,
    profile_with_overrides,
)


def test_signed_temperature_and_sentinel() -> None:
    register = BUILTIN_PROFILE.registers["water_outlet_temperature"]
    assert register.decode(250) == 25.0
    assert register.decode(0xFF06) == -25.0
    assert register.decode(32767) is None


def test_climate_target_defaults() -> None:
    for key in ("heating_target_temperature", "cooling_target_temperature"):
        target = BUILTIN_PROFILE.registers[key]
        assert target.minimum == 10
        assert target.maximum == 35
        assert target.step == 0.5
    assert BUILTIN_PROFILE.registers["dhw_target_temperature"].maximum == 60


def test_write_safety_and_bounds() -> None:
    target = BUILTIN_PROFILE.registers["heating_target_temperature"]
    assert target.encode(25.5) == 255
    with pytest.raises(ValueError):
        target.encode(100)
    with pytest.raises(ValueError):
        BUILTIN_PROFILE.registers["ambient_temperature"].encode(20)


def test_profile_override_does_not_mutate_builtin() -> None:
    custom = profile_with_overrides({"water_outlet_temperature": {"address": 3000, "scale": 0.01}})
    assert custom.registers["water_outlet_temperature"].address == 3000
    assert BUILTIN_PROFILE.registers["water_outlet_temperature"].address == 2046


def test_profile_override_normalizes_and_validates_metadata() -> None:
    custom = profile_with_overrides(
        {
            "mode": {
                "enum": {
                    "0": "hot_water",
                    "1": "heating",
                    "2": "cooling",
                    "7": "eco",
                }
            }
        }
    )
    assert custom.registers["mode"].decode(7) == "eco"
    with pytest.raises(ValueError):
        profile_with_overrides({"mode": {"address": 70000}})
    with pytest.raises(ValueError):
        profile_with_overrides({"mode": {"scale": 0}})
    with pytest.raises(ValueError):
        profile_with_overrides({"mode": {"poll_interval": 4}})


def test_changed_climate_source_creates_custom_profile() -> None:
    profile = profile_with_overrides(None, "water_inlet_temperature")
    assert profile.profile_id == "custom"
    assert profile.current_temperature_key == "water_inlet_temperature"


def test_explicit_unchanged_custom_clone_is_custom() -> None:
    assert profile_with_overrides({}, force_custom=True).profile_id == "custom"


def test_dhw_registers_are_not_polled_when_disabled() -> None:
    profile = profile_for_capabilities(BUILTIN_PROFILE, dhw_enabled=False)
    assert "water_tank_temperature" not in profile.registers
    assert "dhw_target_temperature" not in profile.registers
    assert "fan_2_speed" not in profile.registers


def test_fan_2_register_is_included_when_enabled() -> None:
    profile = profile_for_capabilities(
        BUILTIN_PROFILE,
        dhw_enabled=False,
        fan_2_enabled=True,
    )
    assert "fan_2_speed" in profile.registers


@pytest.mark.parametrize(
    ("data_type", "raw", "expected"),
    [
        (DataType.TEMP, 250, 25.0),
        (DataType.TEMP, 0xFF06, -25.0),
        (DataType.DIGI1, 2, 2),
        (DataType.DIGI2, 2, 20),
        (DataType.DIGI3, 2, 200),
        (DataType.DIGI4, 2, 200),
        (DataType.DIGI5, 25, 2.5),
        (DataType.DIGI6, 25, 0.025),
        (DataType.DIGI9, 25, 0.25),
    ],
)
def test_documented_kaisai_data_types(data_type, raw, expected) -> None:
    assert RegisterDefinition("test", 1, "Test", data_type=data_type).decode(raw) == expected


def test_register_2013_is_digi1_and_2014_is_temp() -> None:
    calculated = BUILTIN_PROFILE.registers["calculated_temperature"]
    compensated = BUILTIN_PROFILE.registers["compensated_temperature"]
    assert calculated.address == 2013
    assert calculated.data_type == DataType.DIGI1
    assert calculated.decode(250) == 250
    assert compensated.address == 2014
    assert compensated.data_type == DataType.TEMP
    assert compensated.decode(250) == 25.0


def test_model_profiles_share_map_but_have_distinct_capabilities() -> None:
    model_09 = BUILTIN_PROFILES[KHX_09_PROFILE_ID]
    model_14 = BUILTIN_PROFILES[KHX_14_PROFILE_ID]
    model_16 = BUILTIN_PROFILES[KHX_16_PROFILE_ID]
    assert model_09.registers is model_14.registers is model_16.registers
    assert model_09.capabilities.electrical_phase == ElectricalPhase.SINGLE_PHASE
    assert model_14.capabilities.electrical_phase == ElectricalPhase.THREE_PHASE
    assert model_16.capabilities.fan_count == 2
    assert model_16.capabilities.supports_fan_2 is True
    with pytest.raises(TypeError):
        model_09.registers["new"] = model_09.registers["power"]
    with pytest.raises(TypeError):
        model_09.registers["mode"].enum[9] = "unsafe"


def test_model_capability_controls_fan_2_entity_register() -> None:
    for profile_id in (KHX_09_PROFILE_ID, KHX_14_PROFILE_ID):
        profile = profile_for_capabilities(BUILTIN_PROFILES[profile_id], dhw_enabled=False)
        assert "fan_2_speed" not in profile.registers
    profile_16 = profile_for_capabilities(BUILTIN_PROFILES[KHX_16_PROFILE_ID], dhw_enabled=False)
    assert "fan_2_speed" in profile_16.registers


def test_non_contiguous_status_bits_and_input_inversion() -> None:
    bits = {definition.key: definition for definition in BUILTIN_PROFILE.bits}
    assert bits["compressor_running"].bit == 0
    assert bits["fan_high_speed_output"].bit == 2
    assert bits["hydraulic_water_tank_heater"].bit == 15
    assert bits["ac_switch"].bit == 9
    assert bits["ac_switch"].inverted is True
    assert bits["ac_switch"].decode(0) is True
    assert bits["ac_switch"].decode(1 << 9) is False


def test_custom_profile_cannot_change_write_authorization() -> None:
    with pytest.raises(ValueError, match="write authorization"):
        profile_with_overrides({"ambient_temperature": {"writable": True}})
    with pytest.raises(ValueError, match="write authorization"):
        profile_with_overrides({"power": {"writable": False}})
    with pytest.raises(ValueError, match="safety limits"):
        profile_with_overrides({"heating_target_temperature": {"maximum": 100}})
    with pytest.raises(ValueError, match="bitfield"):
        profile_with_overrides({"mode": {"data_type": "bitfield"}})


def test_profile_diagnostics_are_json_serializable() -> None:
    encoded = json.dumps(BUILTIN_PROFILES[KHX_16_PROFILE_ID].to_dict())
    assert '"model": "KHX-16PY3"' in encoded
    assert '"effective_scale": 0.1' in encoded
