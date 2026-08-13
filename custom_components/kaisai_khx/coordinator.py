"""KAISAI KHX update coordinator."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any, override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from modbus_connection import ModbusConnection, ModbusError

from .api import KaisaiKhxDevice
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN, FAILURES_UNTIL_UNAVAILABLE
from .faults import ActiveFault, decode_faults
from .profile import RegisterProfile

_LOGGER = logging.getLogger(__name__)

type KaisaiConfigEntry = ConfigEntry[KaisaiCoordinator]


class KaisaiCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(
        self,
        hass: HomeAssistant,
        entry: KaisaiConfigEntry,
        connection: ModbusConnection,
        device: KaisaiKhxDevice,
        profile: RegisterProfile,
    ) -> None:
        global_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        intervals = [definition.poll_interval or global_interval for definition in profile.registers.values()]
        super().__init__(
            hass,
            _LOGGER,
            name=entry.title,
            config_entry=entry,
            update_interval=timedelta(seconds=min(intervals, default=global_interval)),
            always_update=True,
        )
        self.connection = connection
        self.device = device
        self.profile = profile
        self.failed_poll_count = 0
        self.last_successful_update: datetime | None = None
        self._global_interval = global_interval
        self._last_polled: dict[str, float] = {}
        self.device_info = DeviceInfo(
            # The entry remains the same physical HA device when its network
            # endpoint or Modbus unit is changed through reconfigure.
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer="KAISAI",
            model=profile.capabilities.model,
            name=entry.title,
        )

    @property
    def communication_available(self) -> bool:
        return self.failed_poll_count < FAILURES_UNTIL_UNAVAILABLE

    @property
    def active_faults(self) -> list[ActiveFault]:
        """Return model-aware faults decoded from the latest poll."""
        return decode_faults(self.data or {}, self.profile.capabilities)

    @property
    def unavailable_optional_registers(self) -> list[str]:
        """Return optional registers that the device rejected or did not return."""
        data = self.data or {}
        return sorted(
            key for key, definition in self.profile.registers.items() if definition.optional and data.get(key) is None
        )

    @override
    async def _async_update_data(self) -> dict[str, Any]:
        now = time.monotonic()
        register_keys = {
            key
            for key, definition in self.profile.registers.items()
            if now - self._last_polled.get(key, float("-inf")) >= (definition.poll_interval or self._global_interval)
        }
        try:
            updates = await self.device.read_all(register_keys)
        except ModbusError as exc:
            self.failed_poll_count += 1
            if self.failed_poll_count == 1 or self.failed_poll_count == FAILURES_UNTIL_UNAVAILABLE:
                _LOGGER.warning(
                    "Communication with %s failed (%s consecutive failures)",
                    self.config_entry.title,
                    self.failed_poll_count,
                )
            if self.data is not None and self.communication_available:
                return self.data
            raise UpdateFailed(str(exc)) from exc
        if self.failed_poll_count:
            _LOGGER.info("Communication with %s recovered", self.config_entry.title)
        self.failed_poll_count = 0
        self.last_successful_update = dt_util.utcnow()
        self._last_polled.update({key: now for key in register_keys})
        return {**(self.data or {}), **updates}

    async def async_write(self, key: str, value: float | int) -> None:
        await self.device.write(key, value)
        await self.async_request_refresh()
