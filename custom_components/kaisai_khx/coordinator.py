"""KAISAI KHX update coordinator."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Any, override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from modbus_connection import ModbusConnection, ModbusError

from .api import KaisaiKhxDevice
from .const import (
    CONF_CONNECTION_DIAGNOSTICS,
    CONF_CONTROL,
    CONF_COOLING,
    CONF_DEBUG_DIAGNOSTICS,
    CONF_DHW,
    CONF_FAULT_MONITORING,
    CONF_HEATING,
    CONF_INDIVIDUAL_FAULTS,
    CONF_PERFORMANCE_DIAGNOSTICS,
    CONF_POWER_SWITCH,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FAILURES_UNTIL_UNAVAILABLE,
)
from .faults import ActiveFault, decode_faults
from .heat_curve import (
    HEAT_CURVE_STORAGE_VERSION,
    HeatCurveLimitsError,
    HeatCurveSetting,
    HeatCurveSettings,
    heat_curve_storage_key,
    heat_curve_target,
    heat_curve_target_needs_write,
)
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
        self.heat_curve = HeatCurveSettings()
        self.heat_curve_last_target: float | None = None
        self.heat_curve_last_written_target: float | None = None
        self.heat_curve_last_error: str | None = None
        self._write_lock = asyncio.Lock()
        self._heat_curve_store: Store[dict[str, Any]] = Store(
            hass,
            HEAT_CURVE_STORAGE_VERSION,
            heat_curve_storage_key(entry.entry_id),
        )
        self.device_info = DeviceInfo(
            # The entry remains the same physical HA device when its network
            # endpoint or Modbus unit is changed through reconfigure.
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer="KAISAI",
            model=profile.capabilities.model,
            name=entry.title,
        )

    @property
    def debug_diagnostics_enabled(self) -> bool:
        """Return whether every applicable diagnostic entity is enabled."""
        return self.config_entry.options.get(CONF_DEBUG_DIAGNOSTICS, False)

    @property
    def control_enabled(self) -> bool:
        return self.config_entry.options.get(CONF_CONTROL, True)

    @property
    def heating_enabled(self) -> bool:
        return self.config_entry.options.get(CONF_HEATING, True)

    @property
    def cooling_enabled(self) -> bool:
        return self.config_entry.options.get(CONF_COOLING, True)

    @property
    def dhw_enabled(self) -> bool:
        return self.config_entry.options.get(CONF_DHW, False)

    @property
    def power_switch_enabled(self) -> bool:
        return self.config_entry.options.get(CONF_POWER_SWITCH, False)

    @property
    def fault_monitoring_enabled(self) -> bool:
        return self.config_entry.options.get(CONF_FAULT_MONITORING, True) or self.debug_diagnostics_enabled

    @property
    def individual_faults_enabled(self) -> bool:
        return self.config_entry.options.get(CONF_INDIVIDUAL_FAULTS, False) or self.debug_diagnostics_enabled

    @property
    def performance_diagnostics_enabled(self) -> bool:
        return self.config_entry.options.get(CONF_PERFORMANCE_DIAGNOSTICS, True) or self.debug_diagnostics_enabled

    @property
    def connection_diagnostics_enabled(self) -> bool:
        return self.config_entry.options.get(CONF_CONNECTION_DIAGNOSTICS, True) or self.debug_diagnostics_enabled

    async def async_load_heat_curve(self) -> None:
        """Load this device's persistent heat-curve configuration."""
        self.heat_curve = HeatCurveSettings.from_dict(await self._heat_curve_store.async_load())

    async def async_set_heat_curve_setting(
        self, setting: HeatCurveSetting, value: bool | float
    ) -> None:
        """Validate, persist, and apply one heat-curve setting."""
        try:
            updated = self.heat_curve.with_value(setting, value)
        except HeatCurveLimitsError as exc:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_heat_curve_limits",
                translation_placeholders={
                    "low": str(value if setting == "low_limit" else self.heat_curve.low_limit),
                    "high": str(value if setting == "high_limit" else self.heat_curve.high_limit),
                },
            ) from exc
        except ValueError as exc:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_heat_curve_value",
            ) from exc
        await self._heat_curve_store.async_save(updated.as_dict())
        self.heat_curve = updated
        await self.async_apply_heat_curve(self.data or {})
        self.async_update_listeners()

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
        data = {**(self.data or {}), **updates}
        await self.async_apply_heat_curve(data)
        return data

    async def async_apply_heat_curve(self, data: dict[str, Any]) -> None:
        """Apply the active curve without making polling depend on an automatic write."""
        if not self.control_enabled or not self.heating_enabled:
            self.heat_curve_last_target = None
            return
        definition = self.profile.registers[self.profile.heat_target_key]
        target = heat_curve_target(
            self.heat_curve,
            data,
            step=definition.step or 0.5,
            step_origin=definition.minimum or 0.0,
            target_minimum=definition.minimum,
            target_maximum=definition.maximum,
        )
        self.heat_curve_last_target = target
        if target is None:
            return
        current_target = data.get(self.profile.heat_target_key)
        if not heat_curve_target_needs_write(current_target, target):
            self.heat_curve_last_error = None
            return

        async with self._write_lock:
            try:
                await self.device.write(self.profile.heat_target_key, target)
            except (ModbusError, RuntimeError, ValueError) as exc:
                message = str(exc)
                if message != self.heat_curve_last_error:
                    _LOGGER.warning("Unable to apply heat curve for %s: %s", self.config_entry.title, message)
                else:
                    _LOGGER.debug("Heat-curve write still failing for %s: %s", self.config_entry.title, message)
                self.heat_curve_last_error = message
                return
        if self.heat_curve_last_error:
            _LOGGER.info("Heat-curve control recovered for %s", self.config_entry.title)
        self.heat_curve_last_error = None
        self.heat_curve_last_written_target = target
        data[self.profile.heat_target_key] = target

    async def async_write(self, key: str, value: float | int) -> None:
        async with self._write_lock:
            await self.device.write(key, value)
        await self.async_request_refresh()
