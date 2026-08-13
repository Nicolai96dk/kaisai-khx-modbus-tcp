"""Kaisai KHX Modbus TCP integration."""

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from modbus_connection import ModbusError
from modbus_connection.pymodbus import connect_tcp

from .api import KaisaiKhxDevice
from .const import (
    CONF_BASE_PROFILE,
    CONF_CURRENT_TEMP_KEY,
    CONF_CUSTOM_REGISTERS,
    CONF_DHW,
    CONF_ELECTRICAL_PHASE,
    CONF_FAN_2,
    CONF_FAN_COUNT,
    CONF_FAULT_MONITORING,
    CONF_PROFILE,
    CONF_TIMEOUT,
    CONF_UNIT_ID,
    CUSTOM_PROFILE,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    DEFAULT_UNIT_ID,
    PLATFORMS,
)
from .coordinator import KaisaiConfigEntry, KaisaiCoordinator
from .models import GENERIC_PROFILE_ID
from .profile import profile_for_capabilities, profile_with_overrides


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
    selected_profile = entry.data.get(CONF_PROFILE, GENERIC_PROFILE_ID)
    base_profile_id = (
        entry.options.get(CONF_BASE_PROFILE, GENERIC_PROFILE_ID)
        if selected_profile == CUSTOM_PROFILE
        else selected_profile
    )
    profile = profile_with_overrides(
        entry.options.get(CONF_CUSTOM_REGISTERS),
        entry.options.get(CONF_CURRENT_TEMP_KEY),
        force_custom=selected_profile == CUSTOM_PROFILE,
        base_profile_id=base_profile_id,
        capability_overrides={
            "electrical_phase": entry.options.get(CONF_ELECTRICAL_PHASE),
            "fan_count": entry.options.get(CONF_FAN_COUNT),
            "supports_fan_2": entry.options.get(CONF_FAN_2),
            "enable_fault_monitoring": entry.options.get(CONF_FAULT_MONITORING),
        }
        if selected_profile == CUSTOM_PROFILE
        else None,
    )
    profile = profile_for_capabilities(
        profile,
        dhw_enabled=entry.options.get(CONF_DHW, False),
        fan_2_enabled=entry.options.get(CONF_FAN_2, False),
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
