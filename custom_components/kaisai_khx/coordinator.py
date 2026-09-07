"""KAISAI KHX update coordinator."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Any, override

from homeassistant.components.weather import (
    ATTR_FORECAST_TEMP,
    ATTR_FORECAST_TIME,
    SERVICE_GET_FORECASTS,
)
from homeassistant.components.weather import (
    DOMAIN as WEATHER_DOMAIN,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter
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
    CONF_INDOOR_TEMPERATURE_ENTITY,
    CONF_PERFORMANCE_DIAGNOSTICS,
    CONF_POWER_SWITCH,
    CONF_SCAN_INTERVAL,
    CONF_WEATHER_ENTITY,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FAILURES_UNTIL_UNAVAILABLE,
)
from .faults import ActiveFault, decode_faults
from .heat_curve import (
    HEAT_CURVE_STORAGE_VERSION,
    HeatCurveLimitsError,
    HeatCurveMode,
    HeatCurveSetting,
    HeatCurveSettings,
    calculate_heat_curve,
    heat_curve_storage_key,
    heat_curve_target_needs_write,
    indoor_temperature_correction,
    predictive_temperature,
    valid_temperature,
)
from .profile import RegisterProfile

_LOGGER = logging.getLogger(__name__)

FORECAST_REFRESH_SECONDS = 30 * 60
FORECAST_RETRY_SECONDS = 5 * 60
FORECAST_REQUEST_TIMEOUT_SECONDS = 15

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
        self.heat_curve_last_write_time: datetime | None = None
        self.heat_curve_status = "manual"
        self.heat_curve_status_details: dict[str, Any] = {}
        self.heat_curve_effective_ambient: float | None = None
        self.heat_curve_forecast_temperature: float | None = None
        self.heat_curve_indoor_correction: float | None = None
        self._forecast_points: list[tuple[datetime, float]] = []
        self._forecast_last_attempt = float("-inf")
        self._forecast_last_success: datetime | None = None
        self._forecast_error: str | None = None
        self._forecast_lock = asyncio.Lock()
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

    @property
    def weather_entity(self) -> str | None:
        """Return the selected Home Assistant weather entity."""
        return self.config_entry.options.get(CONF_WEATHER_ENTITY)

    @property
    def indoor_temperature_entity(self) -> str | None:
        """Return the selected indoor temperature entity."""
        return self.config_entry.options.get(CONF_INDOOR_TEMPERATURE_ENTITY)

    async def async_load_heat_curve(self) -> None:
        """Load this device's persistent heat-curve configuration."""
        stored = await self._heat_curve_store.async_load()
        self.heat_curve = HeatCurveSettings.from_dict(stored)
        if isinstance(stored, dict) and "mode" not in stored:
            await self._heat_curve_store.async_save(self.heat_curve.as_dict())

    async def async_set_heat_curve_setting(
        self, setting: HeatCurveSetting, value: str | float
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
            if (
                self.failed_poll_count >= FAILURES_UNTIL_UNAVAILABLE
                and self.heat_curve.mode is not HeatCurveMode.MANUAL
            ):
                self._set_heat_curve_status(
                    "suspended",
                    reason="modbus_unavailable",
                    explanation="Automatic control is suspended because Modbus communication is unavailable",
                )
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
        """Apply the selected mode without making polling depend on an automatic write."""
        selected_mode = self.heat_curve.mode
        ambient = valid_temperature(data.get("ambient_temperature"))
        self.heat_curve_last_target = None
        self.heat_curve_effective_ambient = None
        self.heat_curve_forecast_temperature = None
        self.heat_curve_indoor_correction = None

        if selected_mode is HeatCurveMode.MANUAL:
            self._set_heat_curve_status(
                "manual",
                effective_mode=HeatCurveMode.MANUAL.value,
                reason="manual",
                explanation="Automatic heating-target control is disabled",
                ambient_temperature=ambient,
            )
            return
        if not self.control_enabled or not self.heating_enabled:
            self._set_heat_curve_status(
                "suspended",
                reason="heating_control_disabled",
                explanation="Automatic control is unavailable because heating control is disabled",
                ambient_temperature=ambient,
            )
            return
        power = data.get("power_state") or data.get("power")
        if power != "on":
            self._set_heat_curve_status(
                "suspended",
                reason="heat_pump_off",
                explanation="Automatic control is paused because the heat pump is off",
                ambient_temperature=ambient,
            )
            return
        if data.get("mode") != "heating":
            self._set_heat_curve_status(
                "suspended",
                reason="heating_inactive",
                explanation="Automatic control is paused because the heat pump is not in heating mode",
                ambient_temperature=ambient,
            )
            return

        effective_temperature = ambient
        effective_mode = HeatCurveMode.AMBIENT.value
        fallback_reason: str | None = None
        forecast_target_time: datetime | None = None
        indoor_temperature: float | None = None
        indoor_correction = 0.0

        if selected_mode in (HeatCurveMode.PREDICTIVE, HeatCurveMode.PREDICTIVE_INDOOR):
            await self._async_refresh_forecast()
            if self.heat_curve.mode is not selected_mode:
                return
            prediction = predictive_temperature(
                ambient,
                self._forecast_points,
                now=dt_util.utcnow(),
                horizon_hours=self.heat_curve.prediction_horizon,
            )
            if prediction is not None:
                effective_temperature = prediction.effective_temperature
                self.heat_curve_forecast_temperature = prediction.forecast_temperature
                forecast_target_time = prediction.target_time
                effective_mode = HeatCurveMode.PREDICTIVE.value
            elif ambient is not None:
                fallback_reason = self._forecast_error or "forecast_unavailable"
            else:
                self._set_heat_curve_status(
                    "suspended",
                    reason=self._forecast_error or "outdoor_temperature_unavailable",
                    explanation="Neither an hourly forecast nor the KAISAI ambient temperature is available",
                    ambient_temperature=None,
                )
                return

        if selected_mode is HeatCurveMode.AMBIENT and ambient is None:
            self._set_heat_curve_status(
                "suspended",
                reason="ambient_temperature_unavailable",
                explanation="The KAISAI ambient temperature is unavailable",
                ambient_temperature=None,
            )
            return

        if selected_mode is HeatCurveMode.PREDICTIVE_INDOOR:
            indoor_temperature = self._read_indoor_temperature()
            correction = indoor_temperature_correction(self.heat_curve, indoor_temperature)
            if correction is None:
                fallback_reason = (
                    f"{fallback_reason}_and_indoor_temperature_unavailable"
                    if fallback_reason
                    else "indoor_temperature_unavailable"
                )
            else:
                indoor_correction = correction
                self.heat_curve_indoor_correction = correction
                if effective_mode == HeatCurveMode.AMBIENT.value:
                    effective_mode = "ambient_heat_curve_with_indoor_compensation"
                else:
                    effective_mode = HeatCurveMode.PREDICTIVE_INDOOR.value

        if effective_temperature is None:
            self._set_heat_curve_status(
                "suspended",
                reason="outdoor_temperature_unavailable",
                explanation="No usable outdoor temperature is available",
                ambient_temperature=ambient,
            )
            return

        definition = self.profile.registers[self.profile.heat_target_key]
        calculation = calculate_heat_curve(
            self.heat_curve,
            effective_temperature,
            indoor_correction=indoor_correction,
            step=definition.step or 0.5,
            step_origin=definition.minimum or 0.0,
            target_minimum=definition.minimum,
            target_maximum=definition.maximum,
        )
        if calculation is None:
            self._set_heat_curve_status(
                "suspended",
                reason="invalid_effective_limits",
                explanation="The configured limits do not permit a safe heating target",
                ambient_temperature=ambient,
            )
            return
        target = calculation.target
        self.heat_curve_last_target = target
        self.heat_curve_effective_ambient = effective_temperature

        status = "fallback" if fallback_reason else "active"
        if fallback_reason:
            explanation = self._fallback_explanation(fallback_reason, effective_mode)
        else:
            explanation = "Automatic heating-target control is active"
        self._set_heat_curve_status(
            status,
            effective_mode=effective_mode,
            reason=fallback_reason or "active",
            explanation=explanation,
            ambient_temperature=ambient,
            effective_ambient_temperature=effective_temperature,
            forecast_target_time=forecast_target_time,
            indoor_temperature=indoor_temperature,
            indoor_correction=self.heat_curve_indoor_correction,
            raw_target=calculation.raw_target,
            calculated_target=target,
        )
        current_target = data.get(self.profile.heat_target_key)
        if not heat_curve_target_needs_write(current_target, target):
            self.heat_curve_last_error = None
            self.heat_curve_status_details["explanation"] = f"{explanation}; controller target already matches"
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
                self.heat_curve_status = "write_error"
                self.heat_curve_status_details.update(
                    {
                        "reason": "write_failed",
                        "explanation": "The calculated target could not be written to the heat pump",
                        "last_error": message,
                    }
                )
                return
        if self.heat_curve_last_error:
            _LOGGER.info("Heat-curve control recovered for %s", self.config_entry.title)
        self.heat_curve_last_error = None
        self.heat_curve_last_written_target = target
        self.heat_curve_last_write_time = dt_util.utcnow()
        data[self.profile.heat_target_key] = target
        self.heat_curve_status_details.update(
            {
                "explanation": f"{explanation}; calculated target was written",
                "last_applied_target": target,
                "last_write_time": self.heat_curve_last_write_time,
                "last_error": None,
            }
        )

    async def _async_refresh_forecast(self) -> None:
        """Read cached hourly forecast data through Home Assistant's public action."""
        weather_entity = self.weather_entity
        if not weather_entity:
            self._forecast_points = []
            self._forecast_error = "weather_entity_not_configured"
            return
        async with self._forecast_lock:
            now_monotonic = time.monotonic()
            retry_after = FORECAST_RETRY_SECONDS if self._forecast_error else FORECAST_REFRESH_SECONDS
            if now_monotonic - self._forecast_last_attempt < retry_after:
                return
            self._forecast_last_attempt = now_monotonic
            try:
                async with asyncio.timeout(FORECAST_REQUEST_TIMEOUT_SECONDS):
                    response = await self.hass.services.async_call(
                        WEATHER_DOMAIN,
                        SERVICE_GET_FORECASTS,
                        {"type": "hourly"},
                        target={"entity_id": weather_entity},
                        blocking=True,
                        return_response=True,
                    )
                entity_response = response.get(weather_entity) if isinstance(response, dict) else None
                forecasts = entity_response.get("forecast", []) if isinstance(entity_response, dict) else []
                if not isinstance(forecasts, list):
                    raise ValueError("Hourly forecast response was malformed")
                weather_state = self.hass.states.get(weather_entity)
                temperature_unit = (
                    weather_state.attributes.get("temperature_unit")
                    if weather_state is not None
                    else self.hass.config.units.temperature_unit
                )
                points: list[tuple[datetime, float]] = []
                for forecast in forecasts:
                    timestamp = dt_util.parse_datetime(str(forecast.get(ATTR_FORECAST_TIME, "")))
                    temperature = valid_temperature(forecast.get(ATTR_FORECAST_TEMP))
                    if timestamp is None or timestamp.tzinfo is None or temperature is None:
                        continue
                    if temperature_unit and temperature_unit != UnitOfTemperature.CELSIUS:
                        temperature = TemperatureConverter.convert(
                            temperature,
                            temperature_unit,
                            UnitOfTemperature.CELSIUS,
                        )
                    points.append((dt_util.as_utc(timestamp), temperature))
                if len(points) < 2:
                    raise ValueError("Hourly forecast did not contain enough temperature points")
            except (TimeoutError, HomeAssistantError, TypeError, ValueError) as exc:
                self._forecast_points = []
                self._forecast_error = "forecast_unavailable"
                _LOGGER.debug("Unable to read hourly forecast from %s: %s", weather_entity, exc)
                return
            self._forecast_points = sorted(points, key=lambda point: point[0])
            self._forecast_last_success = dt_util.utcnow()
            self._forecast_error = None

    def _read_indoor_temperature(self) -> float | None:
        """Read and normalize the configured indoor temperature to Celsius."""
        entity_id = self.indoor_temperature_entity
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None:
            return None
        try:
            temperature = float(state.state)
            unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
            if unit and unit != UnitOfTemperature.CELSIUS:
                temperature = TemperatureConverter.convert(
                    temperature,
                    unit,
                    UnitOfTemperature.CELSIUS,
                )
        except (TypeError, ValueError):
            return None
        return valid_temperature(temperature)

    def _set_heat_curve_status(
        self,
        status: str,
        *,
        reason: str,
        explanation: str,
        effective_mode: str | None = None,
        **details: Any,
    ) -> None:
        """Update the human- and machine-readable controller status."""
        self.heat_curve_status = status
        self.heat_curve_status_details = {
            "selected_mode": self.heat_curve.mode.value,
            "effective_mode": effective_mode,
            "reason": reason,
            "explanation": explanation,
            "weather_entity": self.weather_entity,
            "forecast_temperature": self.heat_curve_forecast_temperature,
            "prediction_horizon": self.heat_curve.prediction_horizon,
            "forecast_last_success": self._forecast_last_success,
            "forecast_error": self._forecast_error,
            "indoor_sensor": self.indoor_temperature_entity,
            "indoor_target": self.heat_curve.indoor_target,
            "curve_starting_point": self.heat_curve.starting_point,
            "curve_slope": self.heat_curve.curve,
            "low_limit": self.heat_curve.low_limit,
            "high_limit": self.heat_curve.high_limit,
            "last_applied_target": self.heat_curve_last_written_target,
            "last_write_time": self.heat_curve_last_write_time,
            "last_error": self.heat_curve_last_error,
            **details,
        }

    @staticmethod
    def _fallback_explanation(reason: str, effective_mode: str) -> str:
        """Return a concise explanation for a degraded but safe mode."""
        forecast_unavailable = "forecast" in reason or "weather" in reason
        if forecast_unavailable and "indoor" in reason:
            return "Forecast and indoor temperature are unavailable; using the KAISAI ambient heat curve"
        if forecast_unavailable:
            if "indoor_compensation" in effective_mode:
                return "Hourly forecast is unavailable; using ambient heat curve with indoor compensation"
            return "Hourly forecast is unavailable; using the KAISAI ambient heat curve"
        return "Indoor temperature is unavailable; continuing without indoor compensation"

    async def async_write(self, key: str, value: float | int) -> None:
        async with self._write_lock:
            await self.device.write(key, value)
        await self.async_request_refresh()
