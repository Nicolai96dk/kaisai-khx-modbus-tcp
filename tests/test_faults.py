"""Manual-derived fault decoding tests."""

from custom_components.kaisai_khx.faults import (
    FAULT_CODE_DESCRIPTIONS,
    FAULT_DEFINITIONS,
    FaultCategory,
    decode_faults,
)
from custom_components.kaisai_khx.models import (
    KHX_09_PROFILE_ID,
    KHX_14_PROFILE_ID,
    KHX_16_PROFILE_ID,
    MODEL_CAPABILITIES,
)


def _keys(data, profile_id=KHX_09_PROFILE_ID):
    return {fault.definition.key for fault in decode_faults(data, MODEL_CAPABILITIES[profile_id])}


def test_decodes_current_and_repeated_faults() -> None:
    keys = _keys(
        {
            "fault_2085": (1 << 4) | (1 << 8),
            "fault_2087": 1 << 4,
            "fault_2088": (1 << 0) | (1 << 2) | (1 << 3) | (1 << 4),
        }
    )
    assert "high_pressure_protection" in keys
    assert "water_flow_protection" in keys
    assert "repeated_high_pressure" in keys
    assert "repeated_exhaust_over_temperature" in keys
    assert "repeated_water_temperature_difference" in keys
    assert "repeated_outlet_too_low" in keys
    assert "repeated_outlet_too_high" in keys


def test_repeated_bits_are_distinguished_from_current_protection() -> None:
    faults = decode_faults({"fault_2087": 1 << 8}, MODEL_CAPABILITIES[KHX_09_PROFILE_ID])
    assert len(faults) == 1
    assert faults[0].definition.category == FaultCategory.REPEATED_PROTECTION
    assert faults[0].definition.key == "repeated_water_flow"


def test_phase_specific_faults_are_model_aware() -> None:
    data = {"fault_2081": (1 << 3) | (1 << 10) | (1 << 12)}
    single_phase = _keys(data, KHX_09_PROFILE_ID)
    three_phase = _keys(data, KHX_14_PROFILE_ID)
    assert "ac_input_over_current" in single_phase
    assert "dsp_pfc_communication_failure" in single_phase
    assert "input_voltage_phase_loss" not in single_phase
    assert "input_voltage_phase_loss" in three_phase
    assert "ac_input_over_current" not in three_phase
    assert "dsp_pfc_communication_failure" not in three_phase


def test_fan_2_faults_only_apply_to_two_fan_model() -> None:
    data = {"fault_2086": 1 << 4, "fault_2090": (1 << 12) | (1 << 15)}
    for profile_id in (KHX_09_PROFILE_ID, KHX_14_PROFILE_ID):
        assert not {key for key in _keys(data, profile_id) if "fan_2" in key}
    assert {
        "fan_2_overload",
        "fan_2_failure",
        "fan_2_communication_failure",
    }.issubset(_keys(data, KHX_16_PROFILE_ID))


def test_optional_missing_fault_registers_do_not_create_faults() -> None:
    assert decode_faults({}, MODEL_CAPABILITIES[KHX_09_PROFILE_ID]) == []
    assert decode_faults({"fault_2081": None}, MODEL_CAPABILITIES[KHX_09_PROFILE_ID]) == []


def test_fault_code_dictionary_is_separate_and_complete() -> None:
    required = {
        "E04",
        "E11",
        "E032",
        "F01",
        "F031",
        "F032",
        "P01",
        "P181",
        "TP",
    }
    assert required <= FAULT_CODE_DESCRIPTIONS.keys()
    assert FAULT_CODE_DESCRIPTIONS["F03"] == "PFC fault"
    assert FAULT_CODE_DESCRIPTIONS["Pp1"] == "Exhaust pressure sensor fault"
    assert FAULT_CODE_DESCRIPTIONS["P032"] == "Hot-water tank temperature sensor fault"
    mapped_codes = {definition.controller_code for definition in FAULT_DEFINITIONS if definition.controller_code}
    assert mapped_codes <= FAULT_CODE_DESCRIPTIONS.keys()
