"""Operating mode select for KAISAI KHX."""

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import KaisaiConfigEntry
from .entity import KaisaiEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: KaisaiConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    if coordinator.control_enabled and coordinator.dhw_enabled:
        async_add_entities([OperatingModeSelect(coordinator)])


class OperatingModeSelect(KaisaiEntity, SelectEntity):
    _attr_translation_key = "operating_mode"

    def __init__(self, coordinator):
        super().__init__(coordinator, "operating_mode")
        allowed = {"hot_water"}
        if coordinator.heating_enabled:
            allowed.update({"heating", "hot_water_heating"})
        if coordinator.cooling_enabled:
            allowed.update({"cooling", "hot_water_cooling"})
        self._mapping = {
            raw: mode
            for raw, mode in coordinator.profile.registers["mode"].enum.items()
            if mode in allowed
        }
        self._attr_options = list(self._mapping.values())

    @property
    def current_option(self):
        return self.coordinator.data.get("mode")

    async def async_select_option(self, option):
        raw = next((key for key, value in self._mapping.items() if value == option), None)
        if raw is None:
            raise ValueError(f"Unsupported operating mode: {option}")
        await self.coordinator.async_write("mode", raw)
