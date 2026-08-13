"""Climate entity for KAISAI KHX."""

from typing import Any, ClassVar

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACAction, HVACMode
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import KaisaiConfigEntry
from .entity import KaisaiEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: KaisaiConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    if coordinator.control_enabled and (coordinator.heating_enabled or coordinator.cooling_enabled):
        async_add_entities([KaisaiClimate(coordinator)])


class KaisaiClimate(KaisaiEntity, ClimateEntity):
    _attr_translation_key = "climate"
    _attr_hvac_modes: ClassVar[list[HVACMode]] = [HVACMode.OFF]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator):
        super().__init__(coordinator, "climate")
        self._attr_hvac_modes = [HVACMode.OFF]
        if coordinator.heating_enabled:
            self._attr_hvac_modes.append(HVACMode.HEAT)
        if coordinator.cooling_enabled:
            self._attr_hvac_modes.append(HVACMode.COOL)
        target_key = (
            coordinator.profile.heat_target_key
            if coordinator.heating_enabled
            else coordinator.profile.cool_target_key
        )
        target = coordinator.profile.registers[target_key]
        self._attr_min_temp = max(target.minimum or 10, 5)
        self._attr_max_temp = min(target.maximum or 35, 60)
        self._attr_target_temperature_step = target.step or 0.5

    @property
    def current_temperature(self):
        return self.coordinator.data.get(self.coordinator.profile.current_temperature_key)

    @property
    def hvac_mode(self):
        power = self.coordinator.data.get("power_state") or self.coordinator.data.get("power")
        if power != "on":
            return HVACMode.OFF
        mode = {
            "heating": HVACMode.HEAT,
            "hot_water_heating": HVACMode.HEAT,
            "cooling": HVACMode.COOL,
            "hot_water_cooling": HVACMode.COOL,
        }.get(self.coordinator.data.get("mode"))
        if mode in self.hvac_modes:
            return mode
        return HVACMode.HEAT if HVACMode.HEAT in self.hvac_modes else HVACMode.COOL

    @property
    def hvac_action(self):
        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        return {"heating": HVACAction.HEATING, "cooling": HVACAction.COOLING}.get(
            self.coordinator.data.get("operation_status"), HVACAction.IDLE
        )

    @property
    def target_temperature(self):
        key = (
            self.coordinator.profile.cool_target_key
            if self.hvac_mode == HVACMode.COOL
            else self.coordinator.profile.heat_target_key
        )
        return self.coordinator.data.get(key)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode not in self.hvac_modes:
            raise ValueError(f"Unsupported HVAC mode: {hvac_mode}")
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_write("power", 0)
            return
        await self.coordinator.async_write("mode", 1 if hvac_mode == HVACMode.HEAT else 2)
        await self.coordinator.async_write("power", 1)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs[ATTR_TEMPERATURE]
        key = (
            self.coordinator.profile.cool_target_key
            if self.hvac_mode == HVACMode.COOL
            else self.coordinator.profile.heat_target_key
        )
        await self.coordinator.async_write(key, temperature)

    async def async_turn_on(self) -> None:
        await self.coordinator.async_write("power", 1)

    async def async_turn_off(self) -> None:
        await self.coordinator.async_write("power", 0)
