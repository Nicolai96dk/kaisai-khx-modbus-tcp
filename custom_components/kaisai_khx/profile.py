"""Typed register profiles and decoding for KAISAI KHX heat pumps."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields, replace
from enum import StrEnum
from math import isclose
from types import MappingProxyType
from typing import Any

from .models import (
    CUSTOM_PROFILE_ID,
    GENERIC_PROFILE_ID,
    MODEL_CAPABILITIES,
    ModelCapabilities,
    custom_capabilities,
)


class RegisterType(StrEnum):
    """Supported Modbus register tables."""

    HOLDING = "holding"
    INPUT = "input"


class DataType(StrEnum):
    """Documented KAISAI wire data types plus generic custom-profile types."""

    UINT16 = "uint16"
    INT16 = "int16"
    BITFIELD = "bitfield"
    TEMP = "temp"
    DIGI1 = "digi1"
    DIGI2 = "digi2"
    DIGI3 = "digi3"
    DIGI4 = "digi4"
    DIGI5 = "digi5"
    DIGI6 = "digi6"
    DIGI9 = "digi9"
    # Kept so previously saved custom profiles continue to load.
    DIGI = "digi"


_TYPE_SCALE: Mapping[DataType, float] = MappingProxyType(
    {
        DataType.UINT16: 1.0,
        DataType.INT16: 1.0,
        DataType.BITFIELD: 1.0,
        DataType.TEMP: 0.1,
        DataType.DIGI: 1.0,
        DataType.DIGI1: 1.0,
        DataType.DIGI2: 10.0,
        DataType.DIGI3: 100.0,
        DataType.DIGI4: 100.0,
        DataType.DIGI5: 0.1,
        DataType.DIGI6: 0.001,
        DataType.DIGI9: 0.01,
    }
)

# Profiles may remap these semantic controls, but cannot authorize writes.
SEMANTIC_WRITE_ALLOWLIST = frozenset(
    {
        "power",
        "mode",
        "heating_target_temperature",
        "cooling_target_temperature",
        "dhw_target_temperature",
    }
)

# These hard limits are independent of editable profile limits.
INTEGRATION_WRITE_LIMITS: Mapping[str, tuple[float, float]] = MappingProxyType(
    {
        "heating_target_temperature": (5.0, 60.0),
        "cooling_target_temperature": (5.0, 60.0),
        "dhw_target_temperature": (5.0, 65.0),
    }
)


@dataclass(frozen=True, slots=True)
class RegisterDefinition:
    """One profile-defined Modbus register."""

    key: str
    address: int
    name: str
    register_type: RegisterType = RegisterType.HOLDING
    data_type: DataType = DataType.UINT16
    writable: bool = False
    # A multiplier applied after the native KAISAI type resolution.
    scale: float = 1.0
    offset: float = 0.0
    precision: int | None = None
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    enum: Mapping[int, str] = field(default_factory=dict)
    sentinel_values: tuple[int, ...] = ()
    optional: bool = False
    poll_interval: int | None = None

    def __post_init__(self) -> None:
        """Freeze nested enum metadata as part of the profile definition."""
        object.__setattr__(self, "enum", MappingProxyType(dict(self.enum)))

    @property
    def effective_scale(self) -> float:
        """Return native type resolution including a custom multiplier."""
        return _TYPE_SCALE[self.data_type] * self.scale

    def decode(self, raw: int) -> int | float | str | None:
        """Decode one unsigned Modbus word according to its KAISAI type."""
        if raw in self.sentinel_values or (self.data_type == DataType.TEMP and raw == 32767):
            return None
        value = raw
        if self.data_type in (DataType.INT16, DataType.TEMP) and value & 0x8000:
            value -= 0x10000
        if self.enum:
            return self.enum.get(value, f"unknown_{value}")
        decoded = value * self.effective_scale + self.offset
        if self.precision is not None:
            return round(decoded, self.precision)
        return int(decoded) if decoded.is_integer() else decoded

    def encode(self, value: float | int) -> int:
        """Encode and validate a value for a deliberately writable register."""
        if not self.writable:
            raise ValueError(f"Register {self.key} is read only")
        numeric = float(value)
        if self.minimum is not None and numeric < self.minimum:
            raise ValueError(f"Value below minimum {self.minimum}")
        if self.maximum is not None and numeric > self.maximum:
            raise ValueError(f"Value above maximum {self.maximum}")
        if self.step is not None:
            origin = self.minimum or 0.0
            steps = (numeric - origin) / self.step
            if not isclose(steps, round(steps), abs_tol=1e-6):
                raise ValueError(f"Value does not align with step {self.step}")
        if self.enum:
            if not numeric.is_integer() or int(numeric) not in self.enum:
                raise ValueError(f"Value is not present in the enum for {self.key}")
            return int(numeric)
        raw = round((numeric - self.offset) / self.effective_scale)
        if not -32768 <= raw <= 65535:
            raise ValueError("Encoded value is outside a 16-bit register")
        return raw & 0xFFFF


@dataclass(frozen=True, slots=True)
class BitDefinition:
    """One profile-defined status bit."""

    key: str
    register: str
    bit: int
    name: str
    inverted: bool = False

    def decode(self, raw: int) -> bool:
        """Decode the bit, including documented active-low inputs."""
        state = bool(raw & (1 << self.bit))
        return not state if self.inverted else state


@dataclass(frozen=True, slots=True)
class RegisterProfile:
    """A common register map combined with model capabilities."""

    profile_id: str
    name: str
    registers: Mapping[str, RegisterDefinition]
    bits: tuple[BitDefinition, ...]
    capabilities: ModelCapabilities
    current_temperature_key: str = "water_outlet_temperature"
    heat_target_key: str = "heating_target_temperature"
    cool_target_key: str = "cooling_target_temperature"
    power_command_key: str = "power"
    power_state_key: str | None = "power_state"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable diagnostics representation."""
        capabilities = asdict(self.capabilities)
        capabilities["electrical_phase"] = self.capabilities.electrical_phase.value
        return {
            "profile_id": self.profile_id,
            "name": self.name,
            "capabilities": capabilities,
            "registers": {
                key: {
                    **{
                        item.name: (
                            dict(value) if item.name == "enum" else value.value if isinstance(value, StrEnum) else value
                        )
                        for item in fields(definition)
                        if (value := getattr(definition, item.name)) is not None
                    },
                    "effective_scale": definition.effective_scale,
                }
                for key, definition in self.registers.items()
            },
            "bits": [asdict(definition) for definition in self.bits],
            "current_temperature_key": self.current_temperature_key,
            "heat_target_key": self.heat_target_key,
            "cool_target_key": self.cool_target_key,
            "power_command_key": self.power_command_key,
            "power_state_key": self.power_state_key,
        }


def _temp(
    key: str,
    address: int,
    name: str,
    *,
    writable: bool = False,
    optional: bool = False,
    minimum: float | None = None,
    maximum: float | None = None,
    step: float | None = None,
) -> RegisterDefinition:
    return RegisterDefinition(
        key,
        address,
        name,
        data_type=DataType.TEMP,
        writable=writable,
        precision=1,
        minimum=minimum,
        maximum=maximum,
        step=step,
        sentinel_values=(32767,),
        optional=optional,
    )


_COMMON_REGISTERS: dict[str, RegisterDefinition] = {
    "power": RegisterDefinition(
        "power", 1011, "Power command", data_type=DataType.DIGI1, writable=True, enum={0: "off", 1: "on"}
    ),
    "mode": RegisterDefinition(
        "mode",
        1012,
        "Mode",
        data_type=DataType.DIGI1,
        writable=True,
        enum={0: "hot_water", 1: "heating", 2: "cooling", 3: "hot_water_heating", 4: "hot_water_cooling"},
    ),
    "dhw_target_temperature": _temp(
        "dhw_target_temperature",
        1157,
        "Domestic hot water target temperature",
        writable=True,
        optional=True,
        minimum=10,
        maximum=60,
        step=0.5,
    ),
    "heating_target_temperature": _temp(
        "heating_target_temperature",
        1158,
        "Heating target temperature",
        writable=True,
        minimum=10,
        maximum=35,
        step=0.5,
    ),
    "cooling_target_temperature": _temp(
        "cooling_target_temperature",
        1159,
        "Cooling target temperature",
        writable=True,
        minimum=10,
        maximum=35,
        step=0.5,
    ),
    "maximum_water_outlet_temperature": _temp(
        "maximum_water_outlet_temperature", 1238, "Maximum configured water outlet temperature", optional=True
    ),
    "power_state": RegisterDefinition(
        "power_state",
        2011,
        "Power state",
        data_type=DataType.DIGI1,
        enum={0: "off", 1: "on"},
        optional=True,
    ),
    "operation_status": RegisterDefinition(
        "operation_status",
        2012,
        "Operating status",
        data_type=DataType.DIGI1,
        enum={0: "cooling", 1: "heating", 2: "defrosting", 3: "high_temperature_disinfection", 4: "hot_water"},
    ),
    "calculated_temperature": RegisterDefinition(
        "calculated_temperature",
        2013,
        "Calculated current temperature",
        data_type=DataType.DIGI1,
        optional=True,
    ),
    "compensated_temperature": _temp("compensated_temperature", 2014, "Compensated current temperature", optional=True),
    "output_states": RegisterDefinition(
        "output_states", 2019, "Output states", data_type=DataType.BITFIELD, optional=True
    ),
    "input_states": RegisterDefinition(
        "input_states", 2034, "Input states", data_type=DataType.BITFIELD, optional=True
    ),
    "water_inlet_temperature": _temp("water_inlet_temperature", 2045, "Water inlet temperature"),
    "water_outlet_temperature": _temp("water_outlet_temperature", 2046, "Water outlet temperature"),
    "water_tank_temperature": _temp("water_tank_temperature", 2047, "Water tank temperature", optional=True),
    "ambient_temperature": _temp("ambient_temperature", 2048, "Ambient temperature"),
    "compressor_frequency": RegisterDefinition(
        "compressor_frequency", 2072, "Compressor frequency", data_type=DataType.DIGI1
    ),
    "fan_1_speed": RegisterDefinition("fan_1_speed", 2074, "Fan 1 speed", data_type=DataType.DIGI1, optional=True),
    "fan_2_speed": RegisterDefinition("fan_2_speed", 2075, "Fan 2 speed", data_type=DataType.DIGI1, optional=True),
}
for address in (2081, 2082, 2083, 2085, 2086, 2087, 2088, 2089, 2090):
    key = f"fault_{address}"
    _COMMON_REGISTERS[key] = RegisterDefinition(
        key, address, f"Fault register {address}", data_type=DataType.BITFIELD, optional=True
    )

COMMON_REGISTERS: Mapping[str, RegisterDefinition] = MappingProxyType(_COMMON_REGISTERS)

_OUTPUT_BITS = (
    (0, "compressor_running", "Compressor output"),
    (2, "fan_high_speed_output", "Fan high-speed output"),
    (3, "fan_low_speed_output", "Fan low-speed output"),
    (4, "main_circulating_water_pump", "Main circulating water pump"),
    (5, "domestic_hot_water_pump", "Domestic hot water pump"),
    (6, "four_way_valve", "Four-way valve"),
    (7, "electric_heater_stage_1", "Electric heater stage 1"),
    (8, "electric_heater_stage_2", "Electric heater stage 2"),
    (9, "hot_water_3_way_valve", "Hot water 3-way valve"),
    (10, "alarm_output", "Alarm output"),
    (11, "crankcase_heater", "Crankcase heater"),
    (12, "chassis_heater", "Chassis heater"),
    (13, "heating_pump", "Heating pump"),
    (14, "hydraulic_water_circuit_heater", "Hydraulic module water-circuit electric heating"),
    (15, "hydraulic_water_tank_heater", "Hydraulic module water-tank electric heating"),
)
_INPUT_BITS = (
    (0, "high_pressure_switch", "High-pressure switch"),
    (1, "low_pressure_switch", "Low-pressure switch"),
    (2, "water_flow_switch", "Water-flow switch"),
    (3, "electric_heating_overload", "Electric-heating overload switch"),
    (4, "emergency_input", "Emergency input"),
    (5, "air_conditioning_mode_switch", "Air-conditioning mode switch"),
    (6, "hot_water_mode_switch", "Hot-water mode switch"),
    (9, "ac_switch", "A/C switch"),
)
BITS = tuple(BitDefinition(key, "output_states", bit, name) for bit, key, name in _OUTPUT_BITS) + tuple(
    BitDefinition(key, "input_states", bit, name, inverted=True) for bit, key, name in _INPUT_BITS
)

BUILTIN_PROFILES: Mapping[str, RegisterProfile] = MappingProxyType(
    {
        profile_id: RegisterProfile(
            profile_id,
            capabilities.profile_name,
            COMMON_REGISTERS,
            BITS,
            capabilities,
        )
        for profile_id, capabilities in MODEL_CAPABILITIES.items()
    }
)
BUILTIN_PROFILE = BUILTIN_PROFILES[GENERIC_PROFILE_ID]


def get_builtin_profile(profile_id: str) -> RegisterProfile:
    """Return a known immutable built-in profile or the generic profile."""
    return BUILTIN_PROFILES.get(profile_id, BUILTIN_PROFILE)


def profile_with_overrides(
    overrides: dict[str, Any] | None,
    current_key: str | None = None,
    *,
    force_custom: bool = False,
    base_profile_id: str = GENERIC_PROFILE_ID,
    capability_overrides: Mapping[str, Any] | None = None,
) -> RegisterProfile:
    """Return an entry-local customized clone of a built-in profile."""
    base = get_builtin_profile(base_profile_id)
    is_custom = (
        bool(overrides)
        or force_custom
        or bool(capability_overrides)
        or (current_key is not None and current_key != base.current_temperature_key)
    )
    registers = dict(base.registers)
    for key, values in (overrides or {}).items():
        if key not in registers or not isinstance(values, dict):
            continue
        if "writable" in values and bool(values["writable"]) != registers[key].writable:
            raise ValueError("Custom profiles cannot change write authorization")
        allowed = {
            name: value
            for name, value in values.items()
            if name in RegisterDefinition.__dataclass_fields__ and name not in {"key", "name", "writable"}
        }
        if "register_type" in allowed:
            allowed["register_type"] = RegisterType(allowed["register_type"])
        if "data_type" in allowed:
            allowed["data_type"] = DataType(allowed["data_type"])
        if "scale" in allowed:
            allowed["scale"] = float(allowed["scale"])
            if allowed["scale"] == 0:
                raise ValueError("Register scale cannot be zero")
        if "offset" in allowed:
            allowed["offset"] = float(allowed["offset"])
        for field_name in ("minimum", "maximum", "step"):
            if field_name in allowed and allowed[field_name] is not None:
                allowed[field_name] = float(allowed[field_name])
        for field_name in ("address", "precision", "poll_interval"):
            if field_name in allowed and allowed[field_name] is not None:
                allowed[field_name] = int(allowed[field_name])
        if "enum" in allowed:
            allowed["enum"] = {int(enum_key): str(enum_value) for enum_key, enum_value in allowed["enum"].items()}
        if "sentinel_values" in allowed:
            allowed["sentinel_values"] = tuple(int(value) for value in allowed["sentinel_values"])
        updated = replace(registers[key], **allowed)
        if not 0 <= updated.address <= 65535:
            raise ValueError(f"Invalid address for {key}")
        if updated.minimum is not None and updated.maximum is not None and updated.minimum > updated.maximum:
            raise ValueError(f"Minimum exceeds maximum for {key}")
        if updated.step is not None and updated.step <= 0:
            raise ValueError(f"Step must be positive for {key}")
        if updated.poll_interval is not None and updated.poll_interval < 5:
            raise ValueError(f"Polling override must be at least 5 seconds for {key}")
        if key in SEMANTIC_WRITE_ALLOWLIST and updated.data_type == DataType.BITFIELD:
            raise ValueError(f"Writable semantic control {key} cannot use a bitfield type")
        if key == "power" and not {0, 1}.issubset(updated.enum):
            raise ValueError("Power enum must contain off and on values")
        if key == "mode" and not {0, 1, 2}.issubset(updated.enum):
            raise ValueError("Operating-mode enum must contain hot water, heating, and cooling")
        if key in INTEGRATION_WRITE_LIMITS:
            hard_minimum, hard_maximum = INTEGRATION_WRITE_LIMITS[key]
            if updated.minimum is not None and updated.minimum < hard_minimum:
                raise ValueError(f"Minimum for {key} exceeds integration safety limits")
            if updated.maximum is not None and updated.maximum > hard_maximum:
                raise ValueError(f"Maximum for {key} exceeds integration safety limits")
        registers[key] = updated

    if current_key is not None and current_key not in registers:
        raise ValueError("Current temperature register is not part of the profile")

    capabilities = base.capabilities
    if is_custom:
        values = dict(capability_overrides or {})
        capabilities = custom_capabilities(
            base.profile_id,
            electrical_phase=values.get("electrical_phase"),
            fan_count=values.get("fan_count"),
            supports_fan_2=values.get("supports_fan_2"),
            enable_fault_monitoring=values.get("enable_fault_monitoring"),
        )
    return replace(
        base,
        profile_id=CUSTOM_PROFILE_ID if is_custom else base.profile_id,
        name=capabilities.profile_name,
        registers=MappingProxyType(registers),
        capabilities=capabilities,
        current_temperature_key=current_key or base.current_temperature_key,
    )


def profile_for_capabilities(
    profile: RegisterProfile,
    *,
    dhw_enabled: bool,
    fan_2_enabled: bool | None = None,
) -> RegisterProfile:
    """Remove optional registers that do not apply to this device profile."""
    disabled: set[str] = set()
    if not dhw_enabled:
        disabled.update({"dhw_target_temperature", "water_tank_temperature"})

    supports_fan_2 = profile.capabilities.supports_fan_2
    if supports_fan_2 is None:
        supports_fan_2 = bool(fan_2_enabled)
    if not supports_fan_2:
        disabled.add("fan_2_speed")
    if not profile.capabilities.enable_fault_monitoring:
        disabled.update(key for key in profile.registers if key.startswith("fault_"))

    registers = MappingProxyType(
        {key: definition for key, definition in profile.registers.items() if key not in disabled}
    )
    bits = tuple(definition for definition in profile.bits if definition.register in registers)
    return replace(profile, registers=registers, bits=bits)
