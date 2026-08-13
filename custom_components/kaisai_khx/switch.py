"""Power switch for KAISAI KHX."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import KaisaiConfigEntry
from .entity import KaisaiEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: KaisaiConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([PowerSwitch(entry.runtime_data)])


class PowerSwitch(KaisaiEntity, SwitchEntity):
    _attr_translation_key = "power"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

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
