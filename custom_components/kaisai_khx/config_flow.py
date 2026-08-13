"""Config and options flows for KAISAI KHX."""

from __future__ import annotations

import logging
from typing import Any, override

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)
from modbus_connection import ModbusError
from modbus_connection.pymodbus import connect_tcp

from .api import KaisaiKhxDevice
from .const import (
    CONF_CONNECTION_DIAGNOSTICS,
    CONF_CONTROL,
    CONF_COOLING,
    CONF_CURRENT_TEMP_KEY,
    CONF_DEBUG_DIAGNOSTICS,
    CONF_DHW,
    CONF_FAULT_MONITORING,
    CONF_HEATING,
    CONF_INDIVIDUAL_FAULTS,
    CONF_IO_DIAGNOSTICS,
    CONF_MAX_OUTLET_DIAGNOSTIC,
    CONF_PERFORMANCE_DIAGNOSTICS,
    CONF_POWER_STATE_READBACK,
    CONF_POWER_SWITCH,
    CONF_PROFILE,
    CONF_SCAN_INTERVAL,
    CONF_UNIT_ID,
    DEFAULT_CURRENT_TEMP_KEY,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_PROFILE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DEFAULT_UNIT_ID,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .models import KHX_09_PROFILE_ID, KHX_14_PROFILE_ID, KHX_16_PROFILE_ID
from .profile import BUILTIN_PROFILE

_LOGGER = logging.getLogger(__name__)

PROFILE_OPTIONS = [
    {"value": KHX_09_PROFILE_ID, "label": "KAISAI KHX-09PY1"},
    {"value": KHX_14_PROFILE_ID, "label": "KAISAI KHX-14PY3"},
    {"value": KHX_16_PROFILE_ID, "label": "KAISAI KHX-16PY3"},
]
SELECTABLE_PROFILE_IDS = {option["value"] for option in PROFILE_OPTIONS}


def _number_box(minimum: float, maximum: float, *, step: float | None = None) -> NumberSelector:
    """Create a boxed number selector."""
    config: NumberSelectorConfig = {
        "min": minimum,
        "max": maximum,
        "mode": NumberSelectorMode.BOX,
    }
    if step is not None:
        config["step"] = step
    return NumberSelector(config)


def _profile_selector(default: str = DEFAULT_PROFILE) -> SelectSelector:
    """Return the exact-model selector; Generic and Custom are intentionally absent."""
    return SelectSelector(
        SelectSelectorConfig(options=PROFILE_OPTIONS, mode=SelectSelectorMode.DROPDOWN)
    )


def _temperature_sources(dhw_enabled: bool) -> list[dict[str, str]]:
    """Return the permitted climate current-temperature sources."""
    sources = [
        {"value": "water_inlet_temperature", "label": "Water inlet temperature"},
        {"value": "water_outlet_temperature", "label": "Water outlet temperature"},
    ]
    if dhw_enabled:
        sources.append({"value": "water_tank_temperature", "label": "DHW tank temperature"})
    return sources


def connection_schema(defaults: dict[str, Any] | None = None, *, include_profile: bool = False) -> vol.Schema:
    """Build the connection form used by setup and reconfigure."""
    values = defaults or {}
    schema: dict[Any, Any] = {
        vol.Required(CONF_HOST, default=values.get(CONF_HOST, "")): TextSelector(),
        vol.Required(CONF_PORT, default=values.get(CONF_PORT, DEFAULT_PORT)): vol.All(
            _number_box(1, 65535), vol.Coerce(int)
        ),
        vol.Required(CONF_UNIT_ID, default=values.get(CONF_UNIT_ID, DEFAULT_UNIT_ID)): vol.All(
            _number_box(1, 247), vol.Coerce(int)
        ),
        vol.Required(CONF_NAME, default=values.get(CONF_NAME, DEFAULT_NAME)): TextSelector(),
    }
    if include_profile:
        selected = values.get(CONF_PROFILE, DEFAULT_PROFILE)
        if selected not in SELECTABLE_PROFILE_IDS:
            selected = DEFAULT_PROFILE
        schema[vol.Required(CONF_PROFILE, default=selected)] = _profile_selector(selected)
    return vol.Schema(schema)


async def validate_connection(data: dict[str, Any]) -> str | None:
    """Perform one safe read before accepting a Modbus connection."""
    connection = None
    try:
        connection = await connect_tcp(data[CONF_HOST], port=data[CONF_PORT], timeout=DEFAULT_TIMEOUT)
        device = KaisaiKhxDevice(connection.for_unit(data[CONF_UNIT_ID]), BUILTIN_PROFILE)
        await device.read_register(BUILTIN_PROFILE.registers["power"])
    except ModbusError:
        _LOGGER.debug("Unable to validate KAISAI KHX", exc_info=True)
        return "cannot_connect"
    except Exception:
        _LOGGER.exception("Unexpected setup validation error")
        return "unknown"
    finally:
        if connection is not None:
            await connection.close()
    return None


class KaisaiConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure one KAISAI KHX Modbus unit."""

    VERSION = 1
    MINOR_VERSION = 2

    _setup_data: dict[str, Any]
    _setup_options: dict[str, Any]

    @staticmethod
    @override
    def async_get_options_flow(config_entry):
        return KaisaiOptionsFlow()

    @override
    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            unique = f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}:{user_input[CONF_UNIT_ID]}"
            await self.async_set_unique_id(unique)
            self._abort_if_unique_id_configured()
            if error := await validate_connection(user_input):
                errors["base"] = error
            else:
                self._setup_data = dict(user_input)
                self._setup_options = {}
                return await self.async_step_profile()
        return self.async_show_form(step_id="user", data_schema=connection_schema(), errors=errors)

    async def async_step_profile(self, user_input=None):
        """Select one exact built-in model."""
        if user_input is not None:
            self._setup_data[CONF_PROFILE] = user_input[CONF_PROFILE]
            return await self.async_step_features()
        return self.async_show_form(
            step_id="profile",
            data_schema=vol.Schema(
                {vol.Required(CONF_PROFILE, default=DEFAULT_PROFILE): _profile_selector()}
            ),
        )

    async def async_step_features(self, user_input=None):
        """Choose operational and diagnostic features for the selected model."""
        if user_input is not None:
            self._setup_options.update(user_input)
            return await self.async_step_advanced()
        return self.async_show_form(
            step_id="features",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HEATING, default=True): BooleanSelector(),
                    vol.Required(CONF_COOLING, default=True): BooleanSelector(),
                    vol.Required(CONF_DHW, default=False): BooleanSelector(),
                    vol.Required(CONF_CONTROL, default=True): BooleanSelector(),
                    vol.Required(CONF_POWER_SWITCH, default=False): BooleanSelector(),
                    vol.Required(CONF_POWER_STATE_READBACK, default=True): BooleanSelector(),
                    vol.Required(CONF_FAULT_MONITORING, default=True): BooleanSelector(),
                    vol.Required(CONF_INDIVIDUAL_FAULTS, default=False): BooleanSelector(),
                    vol.Required(CONF_PERFORMANCE_DIAGNOSTICS, default=True): BooleanSelector(),
                    vol.Required(CONF_IO_DIAGNOSTICS, default=False): BooleanSelector(),
                    vol.Required(CONF_MAX_OUTLET_DIAGNOSTIC, default=False): BooleanSelector(),
                    vol.Required(CONF_CONNECTION_DIAGNOSTICS, default=True): BooleanSelector(),
                    vol.Required(CONF_DEBUG_DIAGNOSTICS, default=False): BooleanSelector(),
                }
            ),
        )

    async def async_step_advanced(self, user_input=None):
        """Configure only polling and the climate temperature source."""
        dhw_enabled = self._setup_options.get(CONF_DHW, False)
        sources = _temperature_sources(dhw_enabled)
        allowed_sources = {source["value"] for source in sources}
        if user_input is not None:
            values = dict(user_input)
            if values[CONF_CURRENT_TEMP_KEY] not in allowed_sources:
                values[CONF_CURRENT_TEMP_KEY] = DEFAULT_CURRENT_TEMP_KEY
            self._setup_options.update(values)
            return self._async_finish_setup()
        return self.async_show_form(
            step_id="advanced",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
                        _number_box(MIN_SCAN_INTERVAL, MAX_SCAN_INTERVAL), vol.Coerce(int)
                    ),
                    vol.Required(CONF_CURRENT_TEMP_KEY, default=DEFAULT_CURRENT_TEMP_KEY): SelectSelector(
                        SelectSelectorConfig(options=sources, mode=SelectSelectorMode.DROPDOWN)
                    ),
                }
            ),
        )

    def _async_finish_setup(self) -> ConfigFlowResult:
        """Create the completed entry."""
        data = dict(self._setup_data)
        title = data.pop(CONF_NAME)
        return self.async_create_entry(title=title, data=data, options=self._setup_options)

    async def async_step_reconfigure(self, user_input=None):
        """Reconfigure the endpoint and exact model selection."""
        entry = self._get_reconfigure_entry()
        defaults = {**entry.data, CONF_NAME: entry.title}
        errors = {}
        if user_input is not None:
            unique = f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}:{user_input[CONF_UNIT_ID]}"
            if any(
                other.entry_id != entry.entry_id and other.unique_id == unique
                for other in self._async_current_entries()
            ):
                return self.async_abort(reason="already_configured")
            if error := await validate_connection(user_input):
                errors["base"] = error
            else:
                data = dict(user_input)
                title = data.pop(CONF_NAME)
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=unique,
                    title=title,
                    data_updates=data,
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=connection_schema(defaults, include_profile=True),
            errors=errors,
        )


class KaisaiOptionsFlow(OptionsFlowWithReload):
    """Edit the two supported advanced options and reload the entry."""

    @override
    async def async_step_init(self, user_input=None):
        options = self.config_entry.options
        dhw_enabled = options.get(CONF_DHW, False)
        sources = _temperature_sources(dhw_enabled)
        allowed_sources = {source["value"] for source in sources}
        current_source = options.get(CONF_CURRENT_TEMP_KEY, DEFAULT_CURRENT_TEMP_KEY)
        if current_source not in allowed_sources:
            current_source = DEFAULT_CURRENT_TEMP_KEY
        if user_input is not None:
            values = dict(user_input)
            if values[CONF_CURRENT_TEMP_KEY] not in allowed_sources:
                values[CONF_CURRENT_TEMP_KEY] = DEFAULT_CURRENT_TEMP_KEY
            return self.async_create_entry(data={**options, **values})
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): vol.All(_number_box(MIN_SCAN_INTERVAL, MAX_SCAN_INTERVAL), vol.Coerce(int)),
                    vol.Required(CONF_CURRENT_TEMP_KEY, default=current_source): SelectSelector(
                        SelectSelectorConfig(options=sources, mode=SelectSelectorMode.DROPDOWN)
                    ),
                }
            ),
        )
