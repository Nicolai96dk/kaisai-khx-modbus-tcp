"""Kaisai KHX Modbus TCP integration."""

from dataclasses import replace

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from modbus_connection import ModbusError
from modbus_connection.pymodbus import connect_tcp

from .api import KaisaiKhxDevice
from .const import (
    CONF_BASE_PROFILE,
    CONF_COOLING,
    CONF_CURRENT_TEMP_KEY,
    CONF_CUSTOM_REGISTERS,
    CONF_DEBUG_DIAGNOSTICS,
    CONF_DHW,
    CONF_ELECTRICAL_PHASE,
    CONF_FAN_2,
    CONF_FAN_COUNT,
    CONF_FAULT_MONITORING,
    CONF_HEATING,
    CONF_INDIVIDUAL_FAULTS,
    CONF_IO_DIAGNOSTICS,
    CONF_MAX_OUTLET_DIAGNOSTIC,
    CONF_PERFORMANCE_DIAGNOSTICS,
    CONF_POWER_STATE_READBACK,
    CONF_PROFILE,
    CONF_TIMEOUT,
    CONF_UNIT_ID,
    CUSTOM_PROFILE,
    DEFAULT_CURRENT_TEMP_KEY,
    DEFAULT_PORT,
    DEFAULT_PROFILE,
    DEFAULT_TIMEOUT,
    DEFAULT_UNIT_ID,
    PLATFORMS,
)
from .coordinator import KaisaiConfigEntry, KaisaiCoordinator
from .models import GENERIC_PROFILE_ID
from .profile import get_builtin_profile, profile_for_capabilities, profile_with_overrides


async def async_setup_entry(hass: HomeAssistant, entry: KaisaiConfigEntry) -> bool:
    try:
        connection = await connect_tcp(
            entry.data[CONF_HOST],
            port=entry.data.get(CONF_PORT, DEFAULT_PORT),
            timeout=entry.options.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
            message_spacing=entry.options.get("message_spacing", 0.0),
        )
    except ModbusError as exc:
        raise ConfigEntryNotReady("Unable to connect to the Modbus TCP device") from exc
    entry.async_on_unload(connection.close)
    selected_profile = entry.data.get(CONF_PROFILE, DEFAULT_PROFILE)
    if selected_profile == CUSTOM_PROFILE:
        # Compatibility only for v0.1 entries. Custom profiles are no longer
        # offered in setup or options.
        base_profile_id = entry.options.get(CONF_BASE_PROFILE, GENERIC_PROFILE_ID)
        profile = profile_with_overrides(
            entry.options.get(CONF_CUSTOM_REGISTERS),
            entry.options.get(CONF_CURRENT_TEMP_KEY),
            force_custom=True,
            base_profile_id=base_profile_id,
            capability_overrides={
                "electrical_phase": entry.options.get(CONF_ELECTRICAL_PHASE),
                "fan_count": entry.options.get(CONF_FAN_COUNT),
                "supports_fan_2": entry.options.get(CONF_FAN_2),
                "enable_fault_monitoring": entry.options.get(CONF_FAULT_MONITORING),
            },
        )
    else:
        # The legacy generic profile remains loadable, but is not selectable.
        profile = get_builtin_profile(selected_profile)
        profile = replace(
            profile,
            current_temperature_key=entry.options.get(
                CONF_CURRENT_TEMP_KEY, DEFAULT_CURRENT_TEMP_KEY
            ),
        )
    profile = profile_for_capabilities(
        profile,
        dhw_enabled=entry.options.get(CONF_DHW, False),
        fan_2_enabled=entry.options.get(CONF_FAN_2, False),
        heating_enabled=entry.options.get(CONF_HEATING, True),
        cooling_enabled=entry.options.get(CONF_COOLING, True),
        power_state_readback_enabled=entry.options.get(CONF_POWER_STATE_READBACK, True),
        fault_monitoring_enabled=(
            entry.options.get(CONF_FAULT_MONITORING, True)
            or entry.options.get(CONF_INDIVIDUAL_FAULTS, False)
        ),
        performance_diagnostics_enabled=entry.options.get(CONF_PERFORMANCE_DIAGNOSTICS, True),
        io_diagnostics_enabled=entry.options.get(CONF_IO_DIAGNOSTICS, False),
        max_outlet_diagnostic_enabled=entry.options.get(CONF_MAX_OUTLET_DIAGNOSTIC, False),
        debug_diagnostics_enabled=entry.options.get(CONF_DEBUG_DIAGNOSTICS, False),
    )
    device = KaisaiKhxDevice(connection.for_unit(entry.data.get(CONF_UNIT_ID, DEFAULT_UNIT_ID)), profile)
    coordinator = KaisaiCoordinator(hass, entry, connection, device, profile)
    entry.runtime_data = coordinator
    await coordinator.async_config_entry_first_refresh()
    entry.async_on_unload(
        connection.on_connection_lost(lambda: hass.config_entries.async_schedule_reload(entry.entry_id))
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: KaisaiConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
