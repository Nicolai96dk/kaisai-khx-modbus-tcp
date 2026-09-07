"""Power switch for KAISAI KHX."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import KaisaiConfigEntry
from .entity import KaisaiEntity, KaisaiLocalConfigEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: KaisaiConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[SwitchEntity] = []
    if coordinator.control_enabled and coordinator.power_switch_enabled:
        entities.append(PowerSwitch(coordinator))
    if coordinator.control_enabled and coordinator.heating_enabled:
        entities.append(HeatCurveSwitch(coordinator))
    async_add_entities(entities)


class PowerSwitch(KaisaiEntity, SwitchEntity):
    _attr_translation_key = "power"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator):
        super().__init__(coordinator, "power_switch")

    @property
    def is_on(self):
        power = self.coordinator.data.get("power_state") or self.coordinator.data.get("power")
        return power == "on"

    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_write("power", 1)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_write("power", 0)


class HeatCurveSwitch(KaisaiLocalConfigEntity, SwitchEntity):
    """Enable or disable automatic heating-curve control."""

    _attr_translation_key = "heat_curve"

    def __init__(self, coordinator):
        super().__init__(coordinator, "heat_curve_enabled")

    @property
    def is_on(self) -> bool:
        return self.coordinator.heat_curve.enabled

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_heat_curve_setting("enabled", True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_heat_curve_setting("enabled", False)
