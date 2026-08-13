"""Diagnostics support."""

from typing import Any

from homeassistant.core import HomeAssistant

from .const import VERSION
from .coordinator import KaisaiConfigEntry
from .faults import FAULT_DEFINITIONS, FaultCategory, fault_is_applicable, raw_fault_registers


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: KaisaiConfigEntry) -> dict[str, Any]:
    c = entry.runtime_data
    faults = c.active_faults
    fault_registers = raw_fault_registers(c.data or {})
    return {
        "integration_version": VERSION,
        "entry": {"title": entry.title, "unit_id": entry.data.get("unit_id")},
        "profile": c.profile.to_dict(),
        "options": dict(entry.options),
        "connection": {
            "available": c.communication_available,
            "connected": bool(getattr(c.connection, "connected", c.communication_available)),
        },
        "last_successful_update": c.last_successful_update,
        "failed_poll_count": c.failed_poll_count,
        "available_registers": sorted(k for k, v in (c.data or {}).items() if v is not None),
        "unavailable_optional_registers": c.unavailable_optional_registers,
        "faults": {
            "active": [fault.as_dict() for fault in faults],
            "current": [
                fault.as_dict() for fault in faults if fault.definition.category != FaultCategory.REPEATED_PROTECTION
            ],
            "repeated_or_latched": [
                fault.as_dict() for fault in faults if fault.definition.category == FaultCategory.REPEATED_PROTECTION
            ],
            "raw_registers": fault_registers,
            "decode_statistics": {
                "definitions": len(FAULT_DEFINITIONS),
                "applicable_definitions": sum(
                    fault_is_applicable(definition, c.profile.capabilities) for definition in FAULT_DEFINITIONS
                ),
                "active_definitions": len(faults),
                "registers_readable": sum(value is not None for value in fault_registers.values()),
                "registers_unavailable": sum(value is None for value in fault_registers.values()),
            },
        },
        "latest_decoded_data": dict(c.data or {}),
    }
