"""Base entity for KAISAI KHX."""

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import KaisaiCoordinator


class KaisaiEntity(CoordinatorEntity[KaisaiCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: KaisaiCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{key}"
        self._attr_device_info = coordinator.device_info

    @property
    def available(self) -> bool:
        return self.coordinator.communication_available and super().available
