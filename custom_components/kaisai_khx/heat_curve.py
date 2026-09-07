"""Heat-curve calculation and validation for KAISAI KHX."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from math import ceil, floor, isfinite
from typing import Any, Final, Literal

type HeatCurveSetting = Literal["enabled", "starting_point", "curve", "high_limit", "low_limit"]

DEFAULT_HEAT_CURVE_ENABLED: Final = False
DEFAULT_HEAT_CURVE_STARTING_POINT: Final = 30.0
DEFAULT_HEAT_CURVE_CURVE: Final = 0.4
DEFAULT_HEAT_CURVE_HIGH_LIMIT: Final = 35.0
DEFAULT_HEAT_CURVE_LOW_LIMIT: Final = 20.0
HEAT_CURVE_TEMPERATURE_MIN: Final = 10.0
HEAT_CURVE_TEMPERATURE_MAX: Final = 50.0
HEAT_CURVE_CURVE_MIN: Final = 0.0
HEAT_CURVE_CURVE_MAX: Final = 1.0
HEAT_CURVE_STORAGE_VERSION: Final = 1


def heat_curve_storage_key(entry_id: str) -> str:
    """Return the per-config-entry storage key."""
    return f"kaisai_khx.heat_curve.{entry_id}"


class HeatCurveLimitsError(ValueError):
    """Raised when the configured low and high limits conflict."""


@dataclass(frozen=True, slots=True)
class HeatCurveSettings:
    """Persistent user settings for the heating curve."""

    enabled: bool = DEFAULT_HEAT_CURVE_ENABLED
    starting_point: float = DEFAULT_HEAT_CURVE_STARTING_POINT
    curve: float = DEFAULT_HEAT_CURVE_CURVE
    high_limit: float = DEFAULT_HEAT_CURVE_HIGH_LIMIT
    low_limit: float = DEFAULT_HEAT_CURVE_LOW_LIMIT

    @classmethod
    def from_dict(cls, stored: dict[str, Any] | None) -> HeatCurveSettings:
        """Load and validate settings, falling back safely for invalid storage."""
        if not isinstance(stored, dict) or not stored:
            return cls()
        try:
            settings = cls(
                enabled=stored.get("enabled", DEFAULT_HEAT_CURVE_ENABLED) is True,
                starting_point=float(stored.get("starting_point", DEFAULT_HEAT_CURVE_STARTING_POINT)),
                curve=round(float(stored.get("curve", DEFAULT_HEAT_CURVE_CURVE)), 2),
                high_limit=float(stored.get("high_limit", DEFAULT_HEAT_CURVE_HIGH_LIMIT)),
                low_limit=float(stored.get("low_limit", DEFAULT_HEAT_CURVE_LOW_LIMIT)),
            )
            settings.validate()
        except (TypeError, ValueError):
            return cls()
        return settings

    def as_dict(self) -> dict[str, bool | float]:
        """Return JSON-serializable settings."""
        return asdict(self)

    def validate(self) -> None:
        """Validate all integration-level heat-curve safety limits."""
        temperature_values = (self.starting_point, self.high_limit, self.low_limit)
        if any(
            not isfinite(value) or not HEAT_CURVE_TEMPERATURE_MIN <= value <= HEAT_CURVE_TEMPERATURE_MAX
            for value in temperature_values
        ):
            raise ValueError("Heat-curve temperatures must be between 10 and 50 °C")
        if not isfinite(self.curve) or not HEAT_CURVE_CURVE_MIN <= self.curve <= HEAT_CURVE_CURVE_MAX:
            raise ValueError("Heat-curve slope must be between 0 and 1")
        if self.low_limit > self.high_limit:
            raise HeatCurveLimitsError("Heat-curve low limit cannot be higher than its high limit")

    def with_value(self, setting: HeatCurveSetting, value: bool | float) -> HeatCurveSettings:
        """Return settings with one validated value changed."""
        if setting == "enabled":
            updated = replace(self, enabled=bool(value))
        else:
            numeric = float(value)
            if setting == "curve":
                if not isfinite(numeric) or not HEAT_CURVE_CURVE_MIN <= numeric <= HEAT_CURVE_CURVE_MAX:
                    raise ValueError("Heat-curve slope must be between 0 and 1")
                numeric = round(numeric, 2)
            updated = replace(self, **{setting: numeric})
        updated.validate()
        return updated


def heat_curve_target(
    settings: HeatCurveSettings,
    data: dict[str, Any],
    *,
    step: float,
    step_origin: float = 0.0,
    target_minimum: float | None = None,
    target_maximum: float | None = None,
) -> float | None:
    """Calculate an active heating target, or return None when inactive."""
    if not settings.enabled:
        return None
    power = data.get("power_state") or data.get("power")
    if power != "on" or data.get("mode") != "heating":
        return None
    ambient = data.get("ambient_temperature")
    if isinstance(ambient, bool) or not isinstance(ambient, (int, float)) or not isfinite(ambient):
        return None

    effective_low = max(settings.low_limit, target_minimum) if target_minimum is not None else settings.low_limit
    effective_high = min(settings.high_limit, target_maximum) if target_maximum is not None else settings.high_limit
    if effective_low > effective_high:
        return None

    target = ambient * -settings.curve + settings.starting_point
    target = min(max(target, effective_low), effective_high)
    if step > 0:
        aligned_low = ceil((effective_low - step_origin) / step - 1e-9) * step + step_origin
        aligned_high = floor((effective_high - step_origin) / step + 1e-9) * step + step_origin
        if aligned_low > aligned_high:
            return None
        target = round((target - step_origin) / step) * step + step_origin
        target = min(max(target, aligned_low), aligned_high)
    return round(target, 4)


def heat_curve_target_needs_write(current_target: Any, calculated_target: float | None) -> bool:
    """Return whether an active calculated target differs from controller state."""
    if calculated_target is None:
        return False
    if isinstance(current_target, bool) or not isinstance(current_target, (int, float)):
        return True
    return abs(float(current_target) - calculated_target) >= 1e-6
