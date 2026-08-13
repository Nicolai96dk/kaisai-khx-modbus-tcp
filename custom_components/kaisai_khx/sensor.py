"""Sensors for KAISAI KHX."""

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.const import EntityCategory, UnitOfFrequency, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import KaisaiConfigEntry
from .entity import KaisaiEntity
from .faults import raw_fault_registers


@dataclass(frozen=True, kw_only=True)
class Desc(SensorEntityDescription):
    """KAISAI sensor description."""


DESCRIPTIONS = (
    Desc(
        key="water_inlet_temperature",
        translation_key="water_inlet_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    Desc(
        key="water_outlet_temperature",
        translation_key="water_outlet_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    Desc(
        key="water_tank_temperature",
        translation_key="water_tank_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    Desc(
        key="ambient_temperature",
        translation_key="ambient_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    Desc(
        key="compressor_frequency",
        translation_key="compressor_frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    Desc(
        key="operation_status",
        translation_key="operation_status",
        device_class=SensorDeviceClass.ENUM,
        options=["cooling", "heating", "defrosting", "high_temperature_disinfection", "hot_water"],
    ),
    Desc(
        key="calculated_temperature",
        translation_key="calculated_temperature",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    Desc(
        key="compensated_temperature",
        translation_key="compensated_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    Desc(key="fan_1_speed", translation_key="fan_1_speed", entity_category=EntityCategory.DIAGNOSTIC),
    Desc(key="fan_2_speed", translation_key="fan_2_speed", entity_category=EntityCategory.DIAGNOSTIC),
    Desc(
        key="maximum_water_outlet_temperature",
        translation_key="maximum_water_outlet_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    Desc(key="unit_id", translation_key="unit_id", entity_category=EntityCategory.DIAGNOSTIC),
    Desc(key="active_profile", translation_key="active_profile", entity_category=EntityCategory.DIAGNOSTIC),
    Desc(
        key="last_successful_update",
        translation_key="last_successful_update",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    Desc(key="failed_poll_count", translation_key="failed_poll_count", entity_category=EntityCategory.DIAGNOSTIC),
    Desc(
        key="target_temperature",
        translation_key="target_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)

_VIRTUAL_KEYS = {"unit_id", "active_profile", "last_successful_update", "failed_poll_count", "target_temperature"}


async def async_setup_entry(
    hass: HomeAssistant, entry: KaisaiConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Create only entities applicable to the active profile."""
    coordinator = entry.runtime_data
    descriptions = [
        description
        for description in DESCRIPTIONS
        if description.key in coordinator.profile.registers or description.key in _VIRTUAL_KEYS
    ]
    entities: list[SensorEntity] = [KaisaiSensor(coordinator, description) for description in descriptions]
    if coordinator.profile.capabilities.enable_fault_monitoring:
        entities.append(KaisaiActiveFaultSensor(coordinator))
    async_add_entities(entities)


class KaisaiSensor(KaisaiEntity, SensorEntity):
    """A regular or virtual coordinator-backed sensor."""

    def __init__(self, coordinator, description: Desc):
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        key = self.entity_description.key
        if key == "unit_id":
            return self.coordinator.config_entry.data["unit_id"]
        if key == "active_profile":
            return self.coordinator.profile.name
        if key == "last_successful_update":
            return self.coordinator.last_successful_update
        if key == "failed_poll_count":
            return self.coordinator.failed_poll_count
        if key == "target_temperature":
            return self.coordinator.data.get(
                self.coordinator.profile.cool_target_key
                if self.coordinator.data.get("mode") in ("cooling", "hot_water_cooling")
                else self.coordinator.profile.heat_target_key
            )
        return self.coordinator.data.get(key)


class KaisaiActiveFaultSensor(KaisaiEntity, SensorEntity):
    """Human-readable summary of current and repeated Modbus fault bits."""

    _attr_translation_key = "active_fault"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator, "active_fault")

    @property
    def available(self) -> bool:
        values = [value for key, value in (self.coordinator.data or {}).items() if key.startswith("fault_")]
        return super().available and bool(values) and any(value is not None for value in values)

    @property
    def native_value(self) -> str | None:
        faults = self.coordinator.active_faults
        if not faults:
            return None
        if len(faults) > 1:
            return "Multiple faults"
        fault = faults[0]
        return fault.display_code or fault.definition.name

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        faults = self.coordinator.active_faults
        return {
            "active_codes": [fault.display_code for fault in faults if fault.display_code],
            "active_faults": [fault.definition.name for fault in faults],
            "active_categories": sorted({fault.definition.category.value for fault in faults}),
            "active_sources": [
                {"register": fault.definition.register, "bit": fault.definition.bit} for fault in faults
            ],
            "raw_fault_registers": raw_fault_registers(self.coordinator.data or {}),
        }
