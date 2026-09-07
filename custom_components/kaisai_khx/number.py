"""Number entities for KAISAI KHX."""

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import KaisaiConfigEntry
from .entity import KaisaiEntity, KaisaiLocalConfigEntity
from .heat_curve import (
    HEAT_CURVE_CURVE_MAX,
    HEAT_CURVE_CURVE_MIN,
    HEAT_CURVE_TEMPERATURE_MAX,
    HEAT_CURVE_TEMPERATURE_MIN,
    HeatCurveSetting,
)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: KaisaiConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[NumberEntity] = []
    if coordinator.control_enabled and coordinator.dhw_enabled:
        entities.append(DhwTarget(coordinator))
    if coordinator.control_enabled and coordinator.heating_enabled:
        entities.extend(
            [
                HeatCurveNumber(
                    coordinator,
                    "starting_point",
                    "heat_curve_starting_point",
                    HEAT_CURVE_TEMPERATURE_MIN,
                    HEAT_CURVE_TEMPERATURE_MAX,
                    0.5,
                    temperature=True,
                ),
                HeatCurveNumber(
                    coordinator,
                    "curve",
                    "heat_curve_curve",
                    HEAT_CURVE_CURVE_MIN,
                    HEAT_CURVE_CURVE_MAX,
                    0.01,
                ),
                HeatCurveNumber(
                    coordinator,
                    "high_limit",
                    "heat_curve_high_limit",
                    HEAT_CURVE_TEMPERATURE_MIN,
                    HEAT_CURVE_TEMPERATURE_MAX,
                    0.5,
                    temperature=True,
                ),
                HeatCurveNumber(
                    coordinator,
                    "low_limit",
                    "heat_curve_low_limit",
                    HEAT_CURVE_TEMPERATURE_MIN,
                    HEAT_CURVE_TEMPERATURE_MAX,
                    0.5,
                    temperature=True,
                ),
            ]
        )
    async_add_entities(entities)


class DhwTarget(KaisaiEntity, NumberEntity):
    _attr_translation_key = "dhw_target_temperature"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator):
        super().__init__(coordinator, "dhw_target_temperature_number")
        d = coordinator.profile.registers["dhw_target_temperature"]
        self._attr_native_min_value = max(d.minimum or 10, 5)
        self._attr_native_max_value = min(d.maximum or 60, 65)
        self._attr_native_step = d.step or 0.5

    @property
    def native_value(self):
        return self.coordinator.data.get("dhw_target_temperature")

    async def async_set_native_value(self, value):
        await self.coordinator.async_write("dhw_target_temperature", value)


class HeatCurveNumber(KaisaiLocalConfigEntity, NumberEntity):
    """One persistent heat-curve input."""

    _attr_mode = NumberMode.SLIDER

    def __init__(
        self,
        coordinator,
        setting: HeatCurveSetting,
        translation_key: str,
        minimum: float,
        maximum: float,
        step: float,
        *,
        temperature: bool = False,
    ) -> None:
        super().__init__(coordinator, f"heat_curve_{setting}")
        self._setting = setting
        self._attr_translation_key = translation_key
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        self._attr_native_step = step
        if temperature:
            self._attr_device_class = NumberDeviceClass.TEMPERATURE
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    @property
    def native_value(self) -> float:
        return float(getattr(self.coordinator.heat_curve, self._setting))

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_heat_curve_setting(self._setting, value)
