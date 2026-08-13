"""Operating mode select for KAISAI KHX."""

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import KaisaiConfigEntry
from .entity import KaisaiEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: KaisaiConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    if "dhw_target_temperature" in entry.runtime_data.profile.registers:
        async_add_entities([OperatingModeSelect(entry.runtime_data)])


class OperatingModeSelect(KaisaiEntity, SelectEntity):
    _attr_translation_key = "operating_mode"

    def __init__(self, coordinator):
        super().__init__(coordinator, "operating_mode")
        self._mapping = coordinator.profile.registers["mode"].enum
        self._attr_options = list(self._mapping.values())

    @property
    def current_option(self):
        return self.coordinator.data.get("mode")

    async def async_select_option(self, option):
        raw = next((key for key, value in self._mapping.items() if value == option), None)
        if raw is None:
            raise ValueError(f"Unsupported operating mode: {option}")
        await self.coordinator.async_write("mode", raw)
