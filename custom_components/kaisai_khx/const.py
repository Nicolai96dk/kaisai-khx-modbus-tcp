"""Constants for Kaisai KHX."""

from homeassistant.const import Platform

DOMAIN = "kaisai_khx"
NAME = "Kaisai KHX Modbus TCP"
VERSION = "0.3.0"
PLATFORMS = [
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.NUMBER,
]

CONF_UNIT_ID = "unit_id"
CONF_PROFILE = "profile"
# Legacy profile keys are retained only so v0.1 entries can still load.
CONF_BASE_PROFILE = "base_profile"
CONF_DHW = "dhw_enabled"
CONF_FAN_2 = "fan_2_enabled"
CONF_ELECTRICAL_PHASE = "electrical_phase"
CONF_FAN_COUNT = "fan_count"
CONF_FAULT_MONITORING = "enable_fault_monitoring"
CONF_HEATING = "heating_enabled"
CONF_COOLING = "cooling_enabled"
CONF_CONTROL = "control_enabled"
CONF_POWER_SWITCH = "power_switch_enabled"
CONF_POWER_STATE_READBACK = "power_state_readback_enabled"
CONF_INDIVIDUAL_FAULTS = "individual_fault_sensors_enabled"
CONF_PERFORMANCE_DIAGNOSTICS = "performance_diagnostics_enabled"
CONF_IO_DIAGNOSTICS = "io_diagnostics_enabled"
CONF_MAX_OUTLET_DIAGNOSTIC = "max_outlet_diagnostic_enabled"
CONF_CONNECTION_DIAGNOSTICS = "connection_diagnostics_enabled"
CONF_DEBUG_DIAGNOSTICS = "debug_diagnostics_enabled"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_TIMEOUT = "timeout"
CONF_MESSAGE_SPACING = "message_spacing"
CONF_CURRENT_TEMP_KEY = "current_temperature_register"
CONF_CUSTOM_REGISTERS = "custom_registers"

DEFAULT_PORT = 502
DEFAULT_UNIT_ID = 1
DEFAULT_NAME = "Kaisai KHX"
DEFAULT_PROFILE = "kaisai_khx_09py1"
CUSTOM_PROFILE = "custom"
DEFAULT_SCAN_INTERVAL = 20
DEFAULT_TIMEOUT = 10
DEFAULT_CURRENT_TEMP_KEY = "water_outlet_temperature"
MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 300
FAILURES_UNTIL_UNAVAILABLE = 3
