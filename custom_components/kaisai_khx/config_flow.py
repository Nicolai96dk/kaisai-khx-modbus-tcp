"""Config and options flows for KAISAI KHX."""

from __future__ import annotations

import json
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
    TextSelectorConfig,
)
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
    CONF_MESSAGE_SPACING,
    CONF_PROFILE,
    CONF_SCAN_INTERVAL,
    CONF_TIMEOUT,
    CONF_UNIT_ID,
    CUSTOM_PROFILE,
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
from .faults import FAULT_DEFINITIONS
from .models import (
    GENERIC_PROFILE_ID,
    KHX_09_PROFILE_ID,
    KHX_14_PROFILE_ID,
    KHX_16_PROFILE_ID,
    MODEL_CAPABILITIES,
    ElectricalPhase,
)
from .profile import (
    BUILTIN_PROFILE,
    DataType,
    RegisterDefinition,
    RegisterType,
    profile_for_capabilities,
    profile_with_overrides,
)

_LOGGER = logging.getLogger(__name__)

ADDRESS_FIELDS = {f"address_{key}": key for key in BUILTIN_PROFILE.registers}

PROFILE_OPTIONS = [
    {"value": KHX_09_PROFILE_ID, "label": "KAISAI KHX-09PY1"},
    {"value": KHX_14_PROFILE_ID, "label": "KAISAI KHX-14PY3"},
    {"value": KHX_16_PROFILE_ID, "label": "KAISAI KHX-16PY3"},
    {"value": GENERIC_PROFILE_ID, "label": "KAISAI KHX R290 (Generic)"},
    {"value": CUSTOM_PROFILE, "label": "Custom - guided register and capability setup"},
]
BUILTIN_CLONE_OPTIONS = PROFILE_OPTIONS[:-1]


def _number_box(minimum: float, maximum: float, *, step: float | None = None) -> NumberSelector:
    """Create a boxed number selector."""
    return NumberSelector(
        NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            mode=NumberSelectorMode.BOX,
        )
    )


def _register_overrides_from_addresses(values: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return only address values that differ from the built-in profile."""
    overrides: dict[str, dict[str, Any]] = {}
    for field_name, register_key in ADDRESS_FIELDS.items():
        address = int(values[field_name])
        if address != BUILTIN_PROFILE.registers[register_key].address:
            overrides[register_key] = {"address": address}
    return overrides


def _register_metadata_defaults(key: str, overrides: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Build editor defaults from the built-in definition and working overrides."""
    definition = BUILTIN_PROFILE.registers[key]
    values = (
        {**definition.__dict__}
        if hasattr(definition, "__dict__")
        else {field_name: getattr(definition, field_name) for field_name in RegisterDefinition.__dataclass_fields__}
    )
    values.update(overrides.get(key, {}))
    return {
        "register_type": str(values["register_type"]),
        "data_type": str(values["data_type"]),
        "scale": values["scale"],
        "offset": values["offset"],
        "precision": values["precision"] if values["precision"] is not None else -1,
        "minimum": values["minimum"] if values["minimum"] is not None else -32768,
        "maximum": values["maximum"] if values["maximum"] is not None else 65535,
        "step": values["step"] if values["step"] is not None else 0,
        "poll_interval": values["poll_interval"] or 0,
        "enum_mapping": json.dumps(values["enum"], sort_keys=True),
        "sentinel_values": ",".join(str(value) for value in values["sentinel_values"]),
    }


def _metadata_override(key: str, values: dict[str, Any]) -> dict[str, Any]:
    """Normalize one guided metadata form and retain values differing from built-in."""
    definition = BUILTIN_PROFILE.registers[key]
    try:
        enum_mapping = {int(k): str(v) for k, v in json.loads(values["enum_mapping"] or "{}").items()}
        sentinel_values = tuple(int(value.strip()) for value in values["sentinel_values"].split(",") if value.strip())
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as err:
        raise ValueError("Invalid enum mapping or sentinel values") from err
    normalized = {
        "register_type": values["register_type"],
        "data_type": values["data_type"],
        "scale": float(values["scale"]),
        "offset": float(values["offset"]),
        "precision": None if int(values["precision"]) == -1 else int(values["precision"]),
        "minimum": None if float(values["minimum"]) == -32768 else float(values["minimum"]),
        "maximum": None if float(values["maximum"]) == 65535 else float(values["maximum"]),
        "step": None if float(values["step"]) == 0 else float(values["step"]),
        "poll_interval": None if int(values["poll_interval"]) == 0 else int(values["poll_interval"]),
        "enum": enum_mapping,
        "sentinel_values": sentinel_values,
    }
    return {field_name: value for field_name, value in normalized.items() if value != getattr(definition, field_name)}


def connection_schema(defaults: dict[str, Any] | None = None, *, include_profile: bool = False) -> vol.Schema:
    d = defaults or {}
    schema: dict[Any, Any] = {
        vol.Required(CONF_HOST, default=d.get(CONF_HOST, "")): TextSelector(),
        vol.Required(CONF_PORT, default=d.get(CONF_PORT, DEFAULT_PORT)): vol.All(
            NumberSelector(NumberSelectorConfig(min=1, max=65535, mode=NumberSelectorMode.BOX)), vol.Coerce(int)
        ),
        vol.Required(CONF_UNIT_ID, default=d.get(CONF_UNIT_ID, DEFAULT_UNIT_ID)): vol.All(
            NumberSelector(NumberSelectorConfig(min=1, max=247, mode=NumberSelectorMode.BOX)), vol.Coerce(int)
        ),
        vol.Required(CONF_NAME, default=d.get(CONF_NAME, DEFAULT_NAME)): TextSelector(),
    }
    if include_profile:
        schema[vol.Required(CONF_PROFILE, default=d.get(CONF_PROFILE, DEFAULT_PROFILE))] = SelectSelector(
            SelectSelectorConfig(
                options=PROFILE_OPTIONS,
                mode=SelectSelectorMode.DROPDOWN,
            )
        )
    return vol.Schema(schema)


async def validate_connection(data: dict[str, Any]) -> str | None:
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
    VERSION = 1

    _setup_data: dict[str, Any]
    _setup_options: dict[str, Any]
    _working_overrides: dict[str, dict[str, Any]]
    _selected_register: str

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
                self._working_overrides = {}
                return await self.async_step_profile()
        return self.async_show_form(step_id="user", data_schema=connection_schema(), errors=errors)

    async def async_step_profile(self, user_input=None):
        """Choose the built-in profile or open guided custom setup."""
        if user_input is not None:
            self._setup_data[CONF_PROFILE] = user_input[CONF_PROFILE]
            if user_input[CONF_PROFILE] == CUSTOM_PROFILE:
                return await self.async_step_custom_base()
            return self._async_finish_setup()
        return self.async_show_form(
            step_id="profile",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PROFILE, default=DEFAULT_PROFILE): SelectSelector(
                        SelectSelectorConfig(
                            options=PROFILE_OPTIONS,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    def _async_finish_setup(self) -> ConfigFlowResult:
        """Create the entry after optional guided profile editing."""
        data = dict(self._setup_data)
        title = data.pop(CONF_NAME)
        profile_changed = bool(self._working_overrides) or CONF_CURRENT_TEMP_KEY in self._setup_options
        if profile_changed or data[CONF_PROFILE] == CUSTOM_PROFILE:
            data[CONF_PROFILE] = CUSTOM_PROFILE
            self._setup_options[CONF_CUSTOM_REGISTERS] = self._working_overrides
        return self.async_create_entry(
            title=title,
            data=data,
            options=self._setup_options,
        )

    async def async_step_custom_base(self, user_input=None):
        """Choose which immutable built-in profile to clone."""
        if user_input is not None:
            base_profile_id = user_input[CONF_BASE_PROFILE]
            self._setup_options[CONF_BASE_PROFILE] = base_profile_id
            capabilities = MODEL_CAPABILITIES[base_profile_id]
            self._setup_options.setdefault(CONF_ELECTRICAL_PHASE, capabilities.electrical_phase.value)
            self._setup_options.setdefault(CONF_FAN_COUNT, capabilities.fan_count)
            self._setup_options.setdefault(CONF_FAN_2, bool(capabilities.supports_fan_2))
            self._setup_options.setdefault(CONF_FAULT_MONITORING, capabilities.enable_fault_monitoring)
            return await self.async_step_advanced_setup()
        return self.async_show_form(
            step_id="custom_base",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BASE_PROFILE, default=GENERIC_PROFILE_ID): SelectSelector(
                        SelectSelectorConfig(options=BUILTIN_CLONE_OPTIONS, mode=SelectSelectorMode.DROPDOWN)
                    )
                }
            ),
        )

    async def async_step_advanced_setup(self, user_input=None):
        """Show the guided advanced-setup menu."""
        return self.async_show_menu(
            step_id="advanced_setup",
            menu_options=[
                "advanced_capabilities",
                "advanced_communication",
                "advanced_addresses",
                "advanced_register",
                "advanced_climate",
                "advanced_finish",
            ],
        )

    async def async_step_advanced_capabilities(self, user_input=None):
        """Configure optional hardware capabilities during setup."""
        if user_input is not None:
            self._setup_options.update(user_input)
            return await self.async_step_advanced_setup()
        base = MODEL_CAPABILITIES[self._setup_options.get(CONF_BASE_PROFILE, GENERIC_PROFILE_ID)]
        return self.async_show_form(
            step_id="advanced_capabilities",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DHW,
                        default=self._setup_options.get(CONF_DHW, False),
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_ELECTRICAL_PHASE,
                        default=self._setup_options.get(CONF_ELECTRICAL_PHASE, base.electrical_phase.value),
                    ): SelectSelector(SelectSelectorConfig(options=[phase.value for phase in ElectricalPhase])),
                    vol.Required(
                        CONF_FAN_COUNT,
                        default=self._setup_options.get(CONF_FAN_COUNT, base.fan_count) or 0,
                    ): vol.All(_number_box(0, 4), vol.Coerce(int)),
                    vol.Required(
                        CONF_FAN_2,
                        default=self._setup_options.get(CONF_FAN_2, bool(base.supports_fan_2)),
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_FAULT_MONITORING,
                        default=self._setup_options.get(CONF_FAULT_MONITORING, base.enable_fault_monitoring),
                    ): BooleanSelector(),
                }
            ),
        )

    async def async_step_advanced_communication(self, user_input=None):
        """Configure polling and Modbus timing during setup."""
        if user_input is not None:
            self._setup_options.update(user_input)
            return await self.async_step_advanced_setup()
        return self.async_show_form(
            step_id="advanced_communication",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=self._setup_options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): vol.All(
                        _number_box(MIN_SCAN_INTERVAL, MAX_SCAN_INTERVAL),
                        vol.Coerce(int),
                    ),
                    vol.Required(
                        CONF_TIMEOUT,
                        default=self._setup_options.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
                    ): vol.All(_number_box(1, 60, step=1), vol.Coerce(float)),
                    vol.Required(
                        CONF_MESSAGE_SPACING,
                        default=self._setup_options.get(CONF_MESSAGE_SPACING, 0.0),
                    ): vol.All(_number_box(0, 2, step=0.01), vol.Coerce(float)),
                }
            ),
        )

    async def async_step_advanced_addresses(self, user_input=None):
        """Guide the user through all known register addresses."""
        if user_input is not None:
            address_overrides = _register_overrides_from_addresses(user_input)
            for key in BUILTIN_PROFILE.registers:
                existing = self._working_overrides.get(key, {})
                existing.pop("address", None)
                existing.update(address_overrides.get(key, {}))
                if existing:
                    self._working_overrides[key] = existing
                else:
                    self._working_overrides.pop(key, None)
            return await self.async_step_advanced_setup()
        schema: dict[Any, Any] = {}
        for field_name, register_key in ADDRESS_FIELDS.items():
            definition = BUILTIN_PROFILE.registers[register_key]
            default = self._working_overrides.get(register_key, {}).get("address", definition.address)
            schema[vol.Required(field_name, default=default)] = vol.All(
                _number_box(0, 65535),
                vol.Coerce(int),
            )
        return self.async_show_form(
            step_id="advanced_addresses",
            data_schema=vol.Schema(schema),
        )

    async def async_step_advanced_register(self, user_input=None):
        """Choose a register whose complete metadata should be edited."""
        if user_input is not None:
            self._selected_register = user_input["register"]
            return await self.async_step_advanced_register_details()
        options = [{"value": key, "label": definition.name} for key, definition in BUILTIN_PROFILE.registers.items()]
        return self.async_show_form(
            step_id="advanced_register",
            data_schema=vol.Schema(
                {
                    vol.Required("register", default="water_outlet_temperature"): SelectSelector(
                        SelectSelectorConfig(options=options)
                    )
                }
            ),
        )

    async def async_step_advanced_register_details(self, user_input=None):
        """Edit full metadata for one selected register."""
        errors = {}
        if user_input is not None:
            try:
                metadata = _metadata_override(self._selected_register, user_input)
                current = {
                    key: value
                    for key, value in self._working_overrides.get(self._selected_register, {}).items()
                    if key == "address"
                }
                current.update(metadata)
                candidate = dict(self._working_overrides)
                if current:
                    candidate[self._selected_register] = current
                else:
                    candidate.pop(self._selected_register, None)
                profile_with_overrides(candidate)
            except (TypeError, ValueError):
                errors["base"] = "invalid_profile"
            else:
                self._working_overrides = candidate
                return await self.async_step_advanced_setup()
        defaults = _register_metadata_defaults(self._selected_register, self._working_overrides)
        return self.async_show_form(
            step_id="advanced_register_details",
            data_schema=vol.Schema(
                {
                    vol.Required("register_type", default=defaults["register_type"]): SelectSelector(
                        SelectSelectorConfig(options=[value.value for value in RegisterType])
                    ),
                    vol.Required("data_type", default=defaults["data_type"]): SelectSelector(
                        SelectSelectorConfig(options=[value.value for value in DataType])
                    ),
                    vol.Required("scale", default=defaults["scale"]): vol.Coerce(float),
                    vol.Required("offset", default=defaults["offset"]): vol.Coerce(float),
                    vol.Required("precision", default=defaults["precision"]): vol.All(
                        _number_box(-1, 6), vol.Coerce(int)
                    ),
                    vol.Required("minimum", default=defaults["minimum"]): vol.Coerce(float),
                    vol.Required("maximum", default=defaults["maximum"]): vol.Coerce(float),
                    vol.Required("step", default=defaults["step"]): vol.Coerce(float),
                    vol.Required("poll_interval", default=defaults["poll_interval"]): vol.All(
                        _number_box(0, 3600), vol.Coerce(int)
                    ),
                    vol.Required("enum_mapping", default=defaults["enum_mapping"]): TextSelector(
                        TextSelectorConfig(multiline=True)
                    ),
                    vol.Required("sentinel_values", default=defaults["sentinel_values"]): TextSelector(),
                }
            ),
            errors=errors,
            description_placeholders={"register": BUILTIN_PROFILE.registers[self._selected_register].name},
        )

    async def async_step_advanced_climate(self, user_input=None):
        """Configure climate behavior during setup."""
        if user_input is not None:
            submitted = dict(user_input)
            current_key = submitted[CONF_CURRENT_TEMP_KEY]
            candidate = {key: dict(values) for key, values in self._working_overrides.items()}
            for register_key, prefix in (
                (BUILTIN_PROFILE.heat_target_key, "heating"),
                (BUILTIN_PROFILE.cool_target_key, "cooling"),
            ):
                definition = BUILTIN_PROFILE.registers[register_key]
                values = {
                    "minimum": float(submitted[f"{prefix}_minimum"]),
                    "maximum": float(submitted[f"{prefix}_maximum"]),
                    "step": float(submitted[f"{prefix}_step"]),
                }
                existing = candidate.get(register_key, {})
                for field_name, value in values.items():
                    if value == getattr(definition, field_name):
                        existing.pop(field_name, None)
                    else:
                        existing[field_name] = value
                if existing:
                    candidate[register_key] = existing
                else:
                    candidate.pop(register_key, None)
            try:
                profile_with_overrides(candidate, current_key)
            except ValueError:
                return self.async_show_form(
                    step_id="advanced_climate",
                    data_schema=self._advanced_climate_schema(submitted),
                    errors={"base": "invalid_profile"},
                )
            self._working_overrides = candidate
            if current_key == BUILTIN_PROFILE.current_temperature_key:
                self._setup_options.pop(CONF_CURRENT_TEMP_KEY, None)
            else:
                self._setup_options[CONF_CURRENT_TEMP_KEY] = current_key
            return await self.async_step_advanced_setup()
        return self.async_show_form(
            step_id="advanced_climate",
            data_schema=self._advanced_climate_schema(),
        )

    def _advanced_climate_schema(self, submitted: dict[str, Any] | None = None) -> vol.Schema:
        """Build the guided climate schema."""
        submitted = submitted or {}
        keys = [
            {"value": key, "label": definition.name}
            for key, definition in BUILTIN_PROFILE.registers.items()
            if definition.data_type in (DataType.TEMP, DataType.INT16)
        ]
        schema: dict[Any, Any] = {
            vol.Required(
                CONF_CURRENT_TEMP_KEY,
                default=submitted.get(
                    CONF_CURRENT_TEMP_KEY,
                    self._setup_options.get(CONF_CURRENT_TEMP_KEY, BUILTIN_PROFILE.current_temperature_key),
                ),
            ): SelectSelector(SelectSelectorConfig(options=keys))
        }
        for register_key, prefix in (
            (BUILTIN_PROFILE.heat_target_key, "heating"),
            (BUILTIN_PROFILE.cool_target_key, "cooling"),
        ):
            definition = BUILTIN_PROFILE.registers[register_key]
            override = self._working_overrides.get(register_key, {})
            for field_name in ("minimum", "maximum", "step"):
                form_key = f"{prefix}_{field_name}"
                default = submitted.get(form_key, override.get(field_name, getattr(definition, field_name)))
                schema[vol.Required(form_key, default=default)] = vol.Coerce(float)
        return vol.Schema(schema)

    async def async_step_advanced_finish(self, user_input=None):
        """Validate and finish the guided setup."""
        if user_input is None:
            base = MODEL_CAPABILITIES[self._setup_options.get(CONF_BASE_PROFILE, GENERIC_PROFILE_ID)]
            profile_name = f"Custom ({base.profile_name})"
            return self.async_show_form(
                step_id="advanced_finish",
                data_schema=vol.Schema({}),
                description_placeholders={
                    "profile": profile_name,
                    "changes": str(len(self._working_overrides)),
                },
            )
        return self._async_finish_setup()

    async def async_step_reconfigure(self, user_input=None):
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
                options = dict(entry.options)
                if data[CONF_PROFILE] != CUSTOM_PROFILE:
                    options.pop(CONF_CUSTOM_REGISTERS, None)
                    options.pop(CONF_CURRENT_TEMP_KEY, None)
                    options.pop(CONF_BASE_PROFILE, None)
                    options.pop(CONF_ELECTRICAL_PHASE, None)
                    options.pop(CONF_FAN_COUNT, None)
                    options.pop(CONF_FAULT_MONITORING, None)
                    if data[CONF_PROFILE] != GENERIC_PROFILE_ID:
                        options.pop(CONF_FAN_2, None)
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=unique,
                    title=title,
                    data_updates=data,
                    options=options,
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=connection_schema(defaults, include_profile=True),
            errors=errors,
        )


class KaisaiOptionsFlow(OptionsFlowWithReload):
    def _active_profile(self):
        """Build the effective profile without opening a connection."""
        options = self.config_entry.options
        selected = self.config_entry.data.get(CONF_PROFILE, GENERIC_PROFILE_ID)
        base = options.get(CONF_BASE_PROFILE, GENERIC_PROFILE_ID) if selected == CUSTOM_PROFILE else selected
        profile = profile_with_overrides(
            options.get(CONF_CUSTOM_REGISTERS),
            options.get(CONF_CURRENT_TEMP_KEY),
            force_custom=selected == CUSTOM_PROFILE,
            base_profile_id=base,
            capability_overrides={
                "electrical_phase": options.get(CONF_ELECTRICAL_PHASE),
                "fan_count": options.get(CONF_FAN_COUNT),
                "supports_fan_2": options.get(CONF_FAN_2),
                "enable_fault_monitoring": options.get(CONF_FAULT_MONITORING),
            }
            if selected == CUSTOM_PROFILE
            else None,
        )
        return profile_for_capabilities(
            profile,
            dhw_enabled=options.get(CONF_DHW, False),
            fan_2_enabled=options.get(CONF_FAN_2, False),
        )

    @override
    async def async_step_init(self, user_input=None):
        menu = ["general", "climate", "advanced_registers", "test_register", "validate_profile"]
        if self.config_entry.data.get(CONF_PROFILE) == CUSTOM_PROFILE:
            menu.insert(1, "capabilities")
        return self.async_show_menu(
            step_id="init",
            menu_options=menu,
        )

    async def async_step_general(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(data={**self.config_entry.options, **user_input})
        o = self.config_entry.options
        schema: dict[Any, Any] = {
            vol.Required(CONF_SCAN_INTERVAL, default=o.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)): vol.All(
                NumberSelector(
                    NumberSelectorConfig(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL, mode=NumberSelectorMode.BOX)
                ),
                vol.Coerce(int),
            ),
            vol.Required(CONF_DHW, default=o.get(CONF_DHW, False)): BooleanSelector(),
            vol.Required(CONF_TIMEOUT, default=o.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)): vol.All(
                NumberSelector(NumberSelectorConfig(min=1, max=60, step=1, mode=NumberSelectorMode.BOX)),
                vol.Coerce(float),
            ),
            vol.Required(CONF_MESSAGE_SPACING, default=o.get(CONF_MESSAGE_SPACING, 0.0)): vol.All(
                NumberSelector(NumberSelectorConfig(min=0, max=2, step=0.01, mode=NumberSelectorMode.BOX)),
                vol.Coerce(float),
            ),
        }
        selected = self.config_entry.data.get(CONF_PROFILE, GENERIC_PROFILE_ID)
        if selected in (GENERIC_PROFILE_ID, CUSTOM_PROFILE):
            schema[vol.Required(CONF_FAN_2, default=o.get(CONF_FAN_2, False))] = BooleanSelector()
        return self.async_show_form(
            step_id="general",
            data_schema=vol.Schema(schema),
        )

    async def async_step_capabilities(self, user_input=None):
        """Edit descriptive capabilities only for a custom profile."""
        if user_input is not None:
            return self.async_create_entry(data={**self.config_entry.options, **user_input})
        options = self.config_entry.options
        base = MODEL_CAPABILITIES[options.get(CONF_BASE_PROFILE, GENERIC_PROFILE_ID)]
        return self.async_show_form(
            step_id="capabilities",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ELECTRICAL_PHASE,
                        default=options.get(CONF_ELECTRICAL_PHASE, base.electrical_phase.value),
                    ): SelectSelector(SelectSelectorConfig(options=[phase.value for phase in ElectricalPhase])),
                    vol.Required(
                        CONF_FAN_COUNT,
                        default=options.get(CONF_FAN_COUNT, base.fan_count) or 0,
                    ): vol.All(_number_box(0, 4), vol.Coerce(int)),
                    vol.Required(
                        CONF_FAN_2,
                        default=options.get(CONF_FAN_2, bool(base.supports_fan_2)),
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_FAULT_MONITORING,
                        default=options.get(CONF_FAULT_MONITORING, base.enable_fault_monitoring),
                    ): BooleanSelector(),
                }
            ),
        )

    async def async_step_climate(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(data={**self.config_entry.options, **user_input})
        keys = [
            {"value": k, "label": r.name}
            for k, r in BUILTIN_PROFILE.registers.items()
            if r.data_type in (DataType.TEMP, DataType.INT16)
        ]
        return self.async_show_form(
            step_id="climate",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CURRENT_TEMP_KEY,
                        default=self.config_entry.options.get(
                            CONF_CURRENT_TEMP_KEY, BUILTIN_PROFILE.current_temperature_key
                        ),
                    ): SelectSelector(SelectSelectorConfig(options=keys))
                }
            ),
        )

    async def async_step_advanced_registers(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                parsed = json.loads(user_input[CONF_CUSTOM_REGISTERS] or "{}")
                selected = self.config_entry.data.get(CONF_PROFILE, GENERIC_PROFILE_ID)
                base = self.config_entry.options.get(CONF_BASE_PROFILE, selected)
                profile_with_overrides(parsed, force_custom=True, base_profile_id=base)
            except (ValueError, TypeError, json.JSONDecodeError):
                errors["base"] = "invalid_profile"
            else:
                return self.async_create_entry(data={**self.config_entry.options, CONF_CUSTOM_REGISTERS: parsed})
        current = json.dumps(self.config_entry.options.get(CONF_CUSTOM_REGISTERS, {}), indent=2, sort_keys=True)
        return self.async_show_form(
            step_id="advanced_registers",
            data_schema=vol.Schema(
                {vol.Required(CONF_CUSTOM_REGISTERS, default=current): TextSelector(TextSelectorConfig(multiline=True))}
            ),
            errors=errors,
        )

    async def async_step_test_register(self, user_input=None):
        errors = {}
        placeholders = {"result": "Enter a register and submit to perform a safe read."}
        if user_input is not None:
            connection = None
            try:
                connection = await connect_tcp(
                    self.config_entry.data[CONF_HOST],
                    port=self.config_entry.data[CONF_PORT],
                    timeout=self.config_entry.options.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
                )
                unit = connection.for_unit(self.config_entry.data[CONF_UNIT_ID])
                definition = RegisterDefinition(
                    "test",
                    user_input["address"],
                    "Test",
                    RegisterType(user_input["register_type"]),
                    DataType(user_input["data_type"]),
                    scale=user_input["scale"],
                )
                raw, decoded = await KaisaiKhxDevice(unit, BUILTIN_PROFILE).read_register(definition)
                bit_preview = ""
                if definition.data_type == DataType.BITFIELD:
                    active_bits = [
                        fault.name
                        for fault in FAULT_DEFINITIONS
                        if fault.register == user_input["address"] and raw & (1 << fault.bit)
                    ]
                    bit_preview = f"; active bits: {', '.join(active_bits) if active_bits else 'none'}"
                placeholders = {
                    "result": (
                        f"Connection successful — register {user_input['address']}: "
                        f"raw {raw} (0x{raw:04X}), decoded {decoded}{bit_preview}"
                    )
                }
            except Exception as exc:
                errors["base"] = "register_test_failed"
                placeholders = {"result": str(exc)}
            finally:
                if connection is not None:
                    await connection.close()
        return self.async_show_form(
            step_id="test_register",
            data_schema=vol.Schema(
                {
                    vol.Required("address", default=2046): vol.All(
                        NumberSelector(NumberSelectorConfig(min=0, max=65535, mode=NumberSelectorMode.BOX)),
                        vol.Coerce(int),
                    ),
                    vol.Required("register_type", default="holding"): vol.In(["holding", "input"]),
                    vol.Required("data_type", default=DataType.TEMP.value): vol.In(
                        [data_type.value for data_type in DataType]
                    ),
                    vol.Required("scale", default=1.0): vol.Coerce(float),
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_validate_profile(self, user_input=None):
        if user_input is None:
            return self.async_show_form(
                step_id="validate_profile",
                data_schema=vol.Schema({}),
                description_placeholders={"results": "Submit to test required and optional registers."},
            )
        connection = None
        required = []
        optional = []
        try:
            connection = await connect_tcp(self.config_entry.data[CONF_HOST], port=self.config_entry.data[CONF_PORT])
            profile = self._active_profile()
            device = KaisaiKhxDevice(connection.for_unit(self.config_entry.data[CONF_UNIT_ID]), profile)
            for key in ("power", "mode", "water_inlet_temperature", "water_outlet_temperature", "ambient_temperature"):
                try:
                    await device.read_register(device.profile.registers[key])
                    required.append(f"{key}: passed")
                except Exception:
                    required.append(f"{key}: failed")
            optional_keys = [key for key, definition in profile.registers.items() if definition.optional]
            for key in optional_keys:
                try:
                    await device.read_register(device.profile.registers[key])
                    optional.append(f"{key}: available")
                except Exception:
                    optional.append(f"{key}: unavailable")
            for key in ("water_tank_temperature", "fan_2_speed"):
                if key not in profile.registers:
                    optional.append(f"{key}: not applicable to active profile")
        finally:
            if connection is not None:
                await connection.close()
        return self.async_show_form(
            step_id="validate_profile",
            data_schema=vol.Schema({}),
            description_placeholders={"results": "; ".join(required + optional)},
        )
