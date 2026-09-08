"""Local configuration buttons for KAISAI KHX."""

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import KaisaiConfigEntry
from .entity import KaisaiLocalConfigEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KaisaiConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up local maintenance buttons."""
    coordinator = entry.runtime_data
    if coordinator.control_enabled and coordinator.heating_enabled:
        async_add_entities([ResetAdaptiveLearningButton(coordinator)])


class ResetAdaptiveLearningButton(KaisaiLocalConfigEntity, ButtonEntity):
    """Clear only the persistent adaptive-learning model."""

    _attr_translation_key = "reset_adaptive_learning"
    _attr_icon = "mdi:brain"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "reset_adaptive_learning")

    async def async_press(self) -> None:
        """Reset learned corrections without changing Modbus state."""
        await self.coordinator.async_reset_adaptive_learning()
