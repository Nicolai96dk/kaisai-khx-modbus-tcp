"""DHW target number for KAISAI KHX."""

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import KaisaiConfigEntry
from .entity import KaisaiEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: KaisaiConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    if "dhw_target_temperature" in entry.runtime_data.profile.registers:
        async_add_entities([DhwTarget(entry.runtime_data)])


class DhwTarget(KaisaiEntity, NumberEntity):
    _attr_translation_key = "dhw_target_temperature"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator):
        super().__init__(coordinator, "dhw_target_temperature_number")
        d = coordinator.profile.registers["dhw_target_temperature"]
        self._attr_native_min_value = max(d.minimum or 10, 5)
        self._attr_native_max_value = min(d.maximum or 60, 65)
        self._attr_native_step = d.step or 0.5

    @property
    def native_value(self):
        return self.coordinator.data.get("dhw_target_temperature")

    async def async_set_native_value(self, value):
        await self.coordinator.async_write("dhw_target_temperature", value)
