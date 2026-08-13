"""Constants for Kaisai KHX."""

from homeassistant.const import Platform

DOMAIN = "kaisai_khx"
NAME = "Kaisai KHX Modbus TCP"
VERSION = "0.1.0"
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
CONF_BASE_PROFILE = "base_profile"
CONF_DHW = "dhw_enabled"
CONF_FAN_2 = "fan_2_enabled"
CONF_ELECTRICAL_PHASE = "electrical_phase"
CONF_FAN_COUNT = "fan_count"
CONF_FAULT_MONITORING = "enable_fault_monitoring"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_TIMEOUT = "timeout"
CONF_MESSAGE_SPACING = "message_spacing"
CONF_CURRENT_TEMP_KEY = "current_temperature_register"
CONF_CUSTOM_REGISTERS = "custom_registers"

DEFAULT_PORT = 502
DEFAULT_UNIT_ID = 1
DEFAULT_NAME = "Kaisai KHX"
DEFAULT_PROFILE = "kaisai_khx_r290"
CUSTOM_PROFILE = "custom"
DEFAULT_SCAN_INTERVAL = 20
DEFAULT_TIMEOUT = 10
MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 300
FAILURES_UNTIL_UNAVAILABLE = 3
