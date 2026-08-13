"""Typed KAISAI KHX fault metadata and decoder."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from .models import ElectricalPhase, ModelCapabilities


class FaultCategory(StrEnum):
    FAULT = "fault"
    PROTECTION = "protection"
    WARNING = "warning"
    ALARM = "alarm"
    SENSOR_FAULT = "sensor_fault"
    COMMUNICATION_FAULT = "communication_fault"
    REPEATED_PROTECTION = "repeated_protection"


@dataclass(frozen=True, slots=True)
class FaultDefinition:
    register: int
    bit: int
    key: str
    name: str
    category: FaultCategory
    controller_code: str | None = None
    applicable_phases: frozenset[ElectricalPhase] | None = None
    requires_fan_2: bool = False


@dataclass(frozen=True, slots=True)
class ActiveFault:
    definition: FaultDefinition

    @property
    def display_code(self) -> str | None:
        return self.definition.controller_code

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self.definition)
        result["category"] = self.definition.category.value
        if self.definition.applicable_phases is not None:
            result["applicable_phases"] = sorted(phase.value for phase in self.definition.applicable_phases)
        return result


SINGLE_PHASE_ONLY = frozenset({ElectricalPhase.SINGLE_PHASE})
THREE_PHASE_ONLY = frozenset({ElectricalPhase.THREE_PHASE})


def _f(
    register: int,
    bit: int,
    key: str,
    name: str,
    category: FaultCategory = FaultCategory.FAULT,
    code: str | None = None,
    *,
    phases: frozenset[ElectricalPhase] | None = None,
    fan_2: bool = False,
) -> FaultDefinition:
    return FaultDefinition(register, bit, key, name, category, code, phases, fan_2)


FAULT_DEFINITIONS: tuple[FaultDefinition, ...] = (
    _f(2081, 0, "ipm_over_current", "IPM over-current failure"),
    _f(2081, 1, "compressor_drive_failure", "Compressor drive failure"),
    _f(2081, 2, "compressor_over_current", "Compressor over-current"),
    _f(2081, 3, "input_voltage_phase_loss", "Input voltage phase loss", code="F15", phases=THREE_PHASE_ONLY),
    _f(2081, 4, "ipm_current_sampling_failure", "IPM current sampling failure", code="F18"),
    _f(
        2081,
        5,
        "drive_board_over_temperature",
        "Drive board device over-temperature protection",
        FaultCategory.PROTECTION,
    ),
    _f(2081, 6, "pre_charge_failure", "Pre-charge failure"),
    _f(2081, 7, "dc_bus_over_voltage", "DC bus over-voltage", FaultCategory.PROTECTION, "F05"),
    _f(2081, 8, "dc_bus_under_voltage", "DC bus under-voltage", FaultCategory.PROTECTION, "F06"),
    _f(2081, 9, "ac_input_under_voltage", "AC input under-voltage", FaultCategory.PROTECTION, "F07"),
    _f(
        2081,
        10,
        "ac_input_over_current",
        "AC input over-current shutdown",
        FaultCategory.PROTECTION,
        "F08",
        phases=SINGLE_PHASE_ONLY,
    ),
    _f(2081, 11, "input_voltage_sampling_failure", "Input voltage sampling failure", code="F09"),
    _f(
        2081,
        12,
        "dsp_pfc_communication_failure",
        "Communication failure between DSP and PFC",
        FaultCategory.COMMUNICATION_FAULT,
        "F10",
        phases=SINGLE_PHASE_ONLY,
    ),
    _f(
        2081,
        13,
        "drive_board_temperature_sensor_failure",
        "Drive board temperature sensing failure",
        FaultCategory.SENSOR_FAULT,
        "F17",
    ),
    _f(
        2081,
        14,
        "dsp_communication_board_failure",
        "Communication failure between DSP and communication board",
        FaultCategory.COMMUNICATION_FAULT,
        "F11",
    ),
    _f(
        2081,
        15,
        "main_control_communication_failure",
        "Communication failure with main control board",
        FaultCategory.COMMUNICATION_FAULT,
        "F12",
    ),
    _f(2082, 0, "ipm_module_overheat", "IPM module overheat shutdown", FaultCategory.PROTECTION, "F13"),
    _f(2082, 1, "compressor_phase_loss", "Compressor phase loss"),
    _f(2082, 3, "input_current_sampling_failure", "Input current sampling failure"),
    _f(2082, 6, "eeprom_failure", "EEPROM failure"),
    _f(2082, 7, "ac_input_over_voltage", "AC input over-voltage protection", FaultCategory.PROTECTION),
    _f(2082, 15, "compressor_over_speed", "Compressor over-speed protection", FaultCategory.PROTECTION),
    _f(2083, 0, "compressor_current_reduction", "Compressor current frequency-reduction alarm", FaultCategory.ALARM),
    _f(2083, 1, "weak_magnetic_protection", "Compressor weak-magnetic protection alarm", FaultCategory.ALARM, "F16"),
    _f(2083, 2, "power_unit_overheat_alarm", "Power unit overheat alarm", FaultCategory.ALARM, "F20"),
    _f(
        2083,
        4,
        "ac_current_reduction",
        "AC input current frequency-reduction alarm",
        FaultCategory.ALARM,
        "F22",
        phases=SINGLE_PHASE_ONLY,
    ),
    _f(2083, 5, "eeprom_alarm", "EEPROM fault alarm", FaultCategory.ALARM, "F23"),
    _f(2083, 7, "burnt_e2_disable_start", "Burnt E2 / disable-start failure", FaultCategory.ALARM, "F24"),
    _f(
        2085,
        2,
        "heating_return_sensor_failure",
        "Heating return-water temperature sensing failure",
        FaultCategory.SENSOR_FAULT,
    ),
    _f(
        2085,
        3,
        "heating_outlet_sensor_failure",
        "Heating outlet-water temperature sensing failure",
        FaultCategory.SENSOR_FAULT,
    ),
    _f(2085, 4, "high_pressure_protection", "System 1 high-pressure protection", FaultCategory.PROTECTION, "E11"),
    _f(2085, 6, "low_pressure_protection", "System 1 low-pressure protection", FaultCategory.PROTECTION, "E12"),
    _f(2085, 8, "water_flow_protection", "Water-flow switch protection", FaultCategory.PROTECTION, "E032"),
    _f(2085, 9, "electric_heating_overload", "Electric-heating overload protection", FaultCategory.PROTECTION, "E04"),
    _f(2085, 10, "primary_antifreeze", "Primary anti-freezing protection in winter", FaultCategory.PROTECTION, "E19"),
    _f(
        2085,
        11,
        "secondary_antifreeze",
        "Secondary anti-freezing protection in winter",
        FaultCategory.PROTECTION,
        "E29",
    ),
    _f(2085, 12, "system_antifreeze", "Anti-freezing protection of system 1", FaultCategory.PROTECTION, "E171"),
    _f(
        2085,
        14,
        "room_temperature_sensor_failure",
        "Room-temperature sensing failure",
        FaultCategory.SENSOR_FAULT,
        "P42",
    ),
    _f(
        2086,
        0,
        "exhaust_over_temperature",
        "System 1 exhaust over-temperature protection",
        FaultCategory.PROTECTION,
        "P182",
    ),
    _f(2086, 3, "fan_1_overload", "Fan 1 overload speed limit", FaultCategory.PROTECTION),
    _f(2086, 4, "fan_2_overload", "Fan 2 overload speed limit", FaultCategory.PROTECTION, fan_2=True),
    _f(
        2086,
        5,
        "water_temperature_difference",
        "Excessive inlet/outlet water temperature difference protection",
        FaultCategory.PROTECTION,
    ),
    _f(
        2086,
        6,
        "outlet_water_over_temperature",
        "Excessive outlet-water temperature protection",
        FaultCategory.PROTECTION,
    ),
    _f(
        2086,
        7,
        "mixer_outlet_sensor_failure",
        "Water-mixer outlet-water temperature sensing failure",
        FaultCategory.SENSOR_FAULT,
    ),
    _f(
        2086,
        8,
        "hot_water_return_sensor_failure",
        "Hot-water return-water temperature sensing failure",
        FaultCategory.SENSOR_FAULT,
    ),
    _f(
        2086,
        9,
        "hot_water_outlet_sensor_failure",
        "Hot-water outlet-temperature sensing failure",
        FaultCategory.SENSOR_FAULT,
    ),
    _f(
        2087,
        4,
        "repeated_high_pressure",
        "High-pressure protection occurred at least three times",
        FaultCategory.REPEATED_PROTECTION,
        "E11",
    ),
    _f(
        2087,
        6,
        "repeated_low_pressure",
        "Low-pressure protection occurred at least three times",
        FaultCategory.REPEATED_PROTECTION,
        "E12",
    ),
    _f(
        2087,
        8,
        "repeated_water_flow",
        "Water-flow protection occurred at least three times",
        FaultCategory.REPEATED_PROTECTION,
        "E032",
    ),
    _f(
        2087,
        9,
        "repeated_electric_heating",
        "Electric-heating overheat occurred at least three times",
        FaultCategory.REPEATED_PROTECTION,
        "E04",
    ),
    _f(
        2087,
        12,
        "repeated_antifreeze",
        "Anti-freezing protection occurred at least three times",
        FaultCategory.REPEATED_PROTECTION,
        "E171",
    ),
    _f(
        2088,
        0,
        "repeated_exhaust_over_temperature",
        "Exhaust over-temperature occurred at least three times",
        FaultCategory.REPEATED_PROTECTION,
        "P182",
    ),
    _f(
        2088,
        2,
        "repeated_water_temperature_difference",
        "Excessive water temperature difference occurred at least three times",
        FaultCategory.REPEATED_PROTECTION,
    ),
    _f(
        2088,
        3,
        "repeated_outlet_too_low",
        "Outlet-water temperature too low occurred at least three times",
        FaultCategory.REPEATED_PROTECTION,
    ),
    _f(
        2088,
        4,
        "repeated_outlet_too_high",
        "Outlet-water temperature too high occurred at least three times",
        FaultCategory.REPEATED_PROTECTION,
    ),
    _f(
        2089,
        0,
        "inlet_water_sensor_failure",
        "Inlet-water temperature sensing failure",
        FaultCategory.SENSOR_FAULT,
        "P01",
    ),
    _f(
        2089,
        1,
        "outlet_water_sensor_failure",
        "Outlet-water temperature sensing failure",
        FaultCategory.SENSOR_FAULT,
        "P02",
    ),
    _f(2089, 2, "coil_sensor_failure", "System 1 coil temperature sensing failure", FaultCategory.SENSOR_FAULT, "P153"),
    _f(2089, 3, "ambient_sensor_failure", "Ambient-temperature sensing failure", FaultCategory.SENSOR_FAULT, "P04"),
    _f(
        2089,
        4,
        "return_air_sensor_failure",
        "System 1 return-air temperature sensing failure",
        FaultCategory.SENSOR_FAULT,
    ),
    _f(
        2089,
        5,
        "antifreeze_sensor_failure",
        "System 1 anti-freezing temperature sensing failure",
        FaultCategory.SENSOR_FAULT,
        "P191",
    ),
    _f(2089, 6, "outlet_coil_sensor_failure", "Outlet-coil temperature sensing failure", FaultCategory.SENSOR_FAULT),
    _f(
        2089,
        9,
        "evi_inlet_sensor_failure",
        "System 1 EVI inlet-temperature sensing failure",
        FaultCategory.SENSOR_FAULT,
        "P101",
    ),
    _f(
        2089,
        10,
        "evi_outlet_sensor_failure",
        "System 1 EVI outlet-temperature sensing failure",
        FaultCategory.SENSOR_FAULT,
        "P102",
    ),
    _f(
        2089,
        11,
        "exhaust_sensor_failure",
        "System 1 exhaust-temperature sensing failure",
        FaultCategory.SENSOR_FAULT,
        "P181",
    ),
    _f(2089, 13, "pressure_sensor_failure", "System 1 pressure-sensor failure", FaultCategory.SENSOR_FAULT),
    _f(2089, 14, "low_ambient_protection", "Low-ambient-temperature protection", FaultCategory.PROTECTION, "TP"),
    _f(2089, 15, "outlet_water_too_low", "Outlet-water too-low-temperature protection", FaultCategory.PROTECTION),
    _f(
        2090,
        8,
        "water_tank_sensor_failure",
        "Water tank temperature sensing failure",
        FaultCategory.SENSOR_FAULT,
        "P032",
    ),
    _f(2090, 11, "fan_1_failure", "Fan 1 failure", FaultCategory.FAULT, "F031"),
    _f(2090, 12, "fan_2_failure", "Fan 2 failure", FaultCategory.FAULT, "F032", fan_2=True),
    _f(
        2090,
        13,
        "fan_1_communication_failure",
        "Communication failure between main board and DC fan 1",
        FaultCategory.COMMUNICATION_FAULT,
        "E081",
    ),
    _f(
        2090,
        14,
        "hydraulic_module_communication_failure",
        "Communication failure with hydraulic module",
        FaultCategory.COMMUNICATION_FAULT,
    ),
    _f(
        2090,
        15,
        "fan_2_communication_failure",
        "Communication failure between main board and DC fan 2",
        FaultCategory.COMMUNICATION_FAULT,
        "E082",
        fan_2=True,
    ),
)

FAULT_CODE_DESCRIPTIONS: Mapping[str, str] = MappingProxyType(
    {
        "E04": "Electric-heater overheat protection",
        "E08": "Communication fault",
        "E11": "High-pressure protection",
        "E12": "Low-pressure protection",
        "E19": "Primary anti-freezing protection",
        "E29": "Secondary anti-freezing protection",
        "E032": "Water-flow switch protection",
        "E051": "Compressor over-current shutdown fault",
        "E065": "High water outlet-temperature protection",
        "E081": "Main PCB / fan drive communication failure",
        "E082": "Main PCB / fan 2 drive communication failure",
        "E103": "Fan motor overload protection",
        "E171": "Anti-freezing protection",
        "F01": "Compressor activation failure",
        "F03": "PFC fault",
        "F05": "DC bus over-voltage",
        "F06": "DC bus under-voltage",
        "F07": "AC input under-voltage",
        "F08": "AC input over-current",
        "F09": "Input voltage sampling failure",
        "F10": "DSP and PFC communication failure",
        "F11": "Communication fault between DSP and communication board",
        "F12": "Communication failure between main PCB and driver board",
        "F13": "IPM overheat shutdown",
        "F15": "Input-voltage phase loss",
        "F16": "Compressor weak-magnetic protection alarm",
        "F17": "Drive-board temperature sensor fault",
        "F18": "IPM current-sampling fault",
        "F20": "IGBT power-device overheat alarm",
        "F22": "AC input over-current protection alarm",
        "F23": "EEPROM fault alarm",
        "F24": "Destroyed EEPROM / activation-ban alarm",
        "F25": "LP 15 V under-load fault",
        "F26": "IGBT power-device overheat fault",
        "F031": "Fan motor 1 failure",
        "F032": "Fan motor 2 failure",
        "Pp1": "Exhaust pressure sensor fault",
        "Pp2": "Suction pressure sensor fault",
        "TP": "Low ambient temperature protection",
        "P01": "Water inlet temperature sensor fault",
        "P02": "Water outlet temperature sensor fault",
        "P04": "Ambient temperature sensor fault",
        "P17": "Water outlet temperature sensor fault",
        "P032": "Hot-water tank temperature sensor fault",
        "P42": "Room temperature sensor fault",
        "P101": "EVI inlet temperature sensor fault",
        "P102": "EVI outlet temperature sensor fault",
        "P153": "Coil temperature sensor fault",
        "P181": "Exhaust temperature sensor fault",
        "P182": "Exhaust over-temperature",
        "P191": "Anti-freeze temperature sensor fault",
    }
)

FAULT_REGISTER_KEYS: Mapping[int, str] = MappingProxyType(
    {register: f"fault_{register}" for register in (2081, 2082, 2083, 2085, 2086, 2087, 2088, 2089, 2090)}
)


def fault_is_applicable(definition: FaultDefinition, capabilities: ModelCapabilities) -> bool:
    if definition.requires_fan_2 and capabilities.supports_fan_2 is False:
        return False
    return not (
        definition.applicable_phases is not None
        and capabilities.electrical_phase != ElectricalPhase.UNKNOWN
        and capabilities.electrical_phase not in definition.applicable_phases
    )


def decode_faults(data: Mapping[str, Any], capabilities: ModelCapabilities) -> list[ActiveFault]:
    """Decode relevant active bits, retaining unknown-model diagnostics."""
    if not capabilities.enable_fault_monitoring:
        return []
    active: list[ActiveFault] = []
    for definition in FAULT_DEFINITIONS:
        if not fault_is_applicable(definition, capabilities):
            continue
        raw = data.get(FAULT_REGISTER_KEYS[definition.register])
        if raw is not None and int(raw) & (1 << definition.bit):
            active.append(ActiveFault(definition))
    return active


def raw_fault_registers(data: Mapping[str, Any]) -> dict[int, int | None]:
    return {register: data.get(key) for register, key in FAULT_REGISTER_KEYS.items()}
