"""Immutable KAISAI KHX model capability metadata."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType


class ElectricalPhase(StrEnum):
    """Electrical supply topology."""

    UNKNOWN = "unknown"
    SINGLE_PHASE = "single_phase"
    THREE_PHASE = "three_phase"


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    """Capabilities and physical reference metadata for a KHX model."""

    profile_id: str
    profile_name: str
    model: str
    electrical_phase: ElectricalPhase
    fan_count: int | None
    supports_fan_2: bool | None
    enable_fault_monitoring: bool = True
    power_supply: str | None = None
    maximum_power_input_kw: float | None = None
    nominal_water_flow_m3h: float | None = None
    physical_fan_speed_range_rpm: tuple[int, int] | None = None
    tested: bool = False


GENERIC_PROFILE_ID = "kaisai_khx_r290"
KHX_09_PROFILE_ID = "kaisai_khx_09py1"
KHX_14_PROFILE_ID = "kaisai_khx_14py3"
KHX_16_PROFILE_ID = "kaisai_khx_16py3"
CUSTOM_PROFILE_ID = "custom"

MODEL_CAPABILITIES: Mapping[str, ModelCapabilities] = MappingProxyType(
    {
        KHX_09_PROFILE_ID: ModelCapabilities(
            KHX_09_PROFILE_ID,
            "KAISAI KHX-09PY1",
            "KHX-09PY1",
            ElectricalPhase.SINGLE_PHASE,
            1,
            False,
            power_supply="220-240 V / 50 Hz",
            maximum_power_input_kw=3.0,
            nominal_water_flow_m3h=1.0,
            physical_fan_speed_range_rpm=(220, 600),
            tested=True,
        ),
        KHX_14_PROFILE_ID: ModelCapabilities(
            KHX_14_PROFILE_ID,
            "KAISAI KHX-14PY3",
            "KHX-14PY3",
            ElectricalPhase.THREE_PHASE,
            1,
            False,
            power_supply="380-415 V / 3N~ / 50 Hz",
            maximum_power_input_kw=5.3,
            nominal_water_flow_m3h=1.7,
            physical_fan_speed_range_rpm=(220, 600),
        ),
        KHX_16_PROFILE_ID: ModelCapabilities(
            KHX_16_PROFILE_ID,
            "KAISAI KHX-16PY3",
            "KHX-16PY3",
            ElectricalPhase.THREE_PHASE,
            2,
            True,
            power_supply="380-415 V / 3N~ / 50 Hz",
            maximum_power_input_kw=9.0,
            nominal_water_flow_m3h=2.9,
            physical_fan_speed_range_rpm=(300, 750),
        ),
        GENERIC_PROFILE_ID: ModelCapabilities(
            GENERIC_PROFILE_ID,
            "KAISAI KHX R290 (Generic)",
            "KHX R290",
            ElectricalPhase.UNKNOWN,
            None,
            None,
        ),
    }
)


def custom_capabilities(
    base_profile_id: str,
    *,
    electrical_phase: str | None = None,
    fan_count: int | None = None,
    supports_fan_2: bool | None = None,
    enable_fault_monitoring: bool | None = None,
) -> ModelCapabilities:
    """Create editable custom capability metadata from an immutable built-in."""
    base = MODEL_CAPABILITIES.get(base_profile_id, MODEL_CAPABILITIES[GENERIC_PROFILE_ID])
    return replace(
        base,
        profile_id=CUSTOM_PROFILE_ID,
        profile_name=f"Custom ({base.profile_name})",
        electrical_phase=ElectricalPhase(electrical_phase) if electrical_phase else base.electrical_phase,
        fan_count=None if fan_count == 0 else (fan_count if fan_count is not None else base.fan_count),
        supports_fan_2=supports_fan_2 if supports_fan_2 is not None else base.supports_fan_2,
        enable_fault_monitoring=(
            enable_fault_monitoring if enable_fault_monitoring is not None else base.enable_fault_monitoring
        ),
        tested=False,
    )
