"""Problem and optional diagnostic binary sensors for KAISAI KHX."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import KaisaiConfigEntry
from .entity import KaisaiEntity
from .faults import FAULT_DEFINITIONS, FaultDefinition, fault_is_applicable


async def async_setup_entry(
    hass: HomeAssistant, entry: KaisaiConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Create aggregate faults and applicable optional diagnostic bits."""
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [KaisaiBitSensor(coordinator, bit) for bit in coordinator.profile.bits]
    if coordinator.profile.capabilities.enable_fault_monitoring:
        entities.append(KaisaiFaultSensor(coordinator))
        entities.extend(
            KaisaiIndividualFaultSensor(coordinator, definition)
            for definition in FAULT_DEFINITIONS
            if fault_is_applicable(definition, coordinator.profile.capabilities)
            and f"fault_{definition.register}" in coordinator.profile.registers
        )
    async_add_entities(entities)


class KaisaiFaultSensor(KaisaiEntity, BinarySensorEntity):
    """Enabled aggregate problem signal for all applicable fault registers."""

    _attr_translation_key = "fault"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator):
        super().__init__(coordinator, "fault")

    @property
    def is_on(self) -> bool | None:
        fault_values = [value for key, value in (self.coordinator.data or {}).items() if key.startswith("fault_")]
        if not fault_values or all(value is None for value in fault_values):
            return None
        return bool(self.coordinator.active_faults)


class KaisaiBitSensor(KaisaiEntity, BinarySensorEntity):
    """Disabled-by-default raw output/input status bit."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, bit):
        super().__init__(coordinator, bit.key)
        self._bit = bit
        self._attr_name = bit.name

    @property
    def is_on(self):
        value = self.coordinator.data.get(self._bit.register)
        if value is None:
            return None
        return self._bit.decode(int(value))


class KaisaiIndividualFaultSensor(KaisaiEntity, BinarySensorEntity):
    """Disabled-by-default binary sensor for one documented fault bit."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, definition: FaultDefinition):
        super().__init__(coordinator, f"fault_{definition.register}_{definition.bit}")
        self._definition = definition
        self._attr_name = definition.name

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.data.get(f"fault_{self._definition.register}")
        if value is None:
            return None
        return bool(int(value) & (1 << self._definition.bit))

    @property
    def extra_state_attributes(self) -> dict[str, str | int]:
        attributes: dict[str, str | int] = {
            "register": self._definition.register,
            "bit": self._definition.bit,
            "category": self._definition.category.value,
        }
        if self._definition.controller_code:
            attributes["controller_code"] = self._definition.controller_code
        return attributes
