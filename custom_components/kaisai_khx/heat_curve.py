"""Heat-curve calculation and validation for KAISAI KHX."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from itertools import pairwise
from math import ceil, floor, isfinite
from typing import Any, Final, Literal


class HeatCurveMode(StrEnum):
    """Available automatic heating-target modes."""

    MANUAL = "manual"
    AMBIENT = "ambient_heat_curve"
    PREDICTIVE = "predictive_heat_curve"
    PREDICTIVE_INDOOR = "predictive_indoor"
    ADAPTIVE = "adaptive_learning"


type HeatCurveSetting = Literal[
    "mode",
    "starting_point",
    "curve",
    "high_limit",
    "low_limit",
    "prediction_horizon",
    "indoor_target",
]

DEFAULT_HEAT_CURVE_MODE: Final = HeatCurveMode.MANUAL
DEFAULT_HEAT_CURVE_STARTING_POINT: Final = 30.0
DEFAULT_HEAT_CURVE_CURVE: Final = 0.4
DEFAULT_HEAT_CURVE_HIGH_LIMIT: Final = 35.0
DEFAULT_HEAT_CURVE_LOW_LIMIT: Final = 20.0
DEFAULT_PREDICTION_HORIZON: Final = 8
DEFAULT_INDOOR_TARGET: Final = 21.0
HEAT_CURVE_TEMPERATURE_MIN: Final = 10.0
HEAT_CURVE_TEMPERATURE_MAX: Final = 50.0
HEAT_CURVE_CURVE_MIN: Final = 0.0
HEAT_CURVE_CURVE_MAX: Final = 1.0
PREDICTION_HORIZON_MIN: Final = 1
PREDICTION_HORIZON_MAX: Final = 12
INDOOR_TARGET_MIN: Final = 15.0
INDOOR_TARGET_MAX: Final = 25.0
INDOOR_CORRECTION_FACTOR: Final = 1.0
INDOOR_CORRECTION_LIMIT: Final = 2.0
HEAT_CURVE_STORAGE_VERSION: Final = 1


def heat_curve_storage_key(entry_id: str) -> str:
    """Return the per-config-entry storage key."""
    return f"kaisai_khx.heat_curve.{entry_id}"


class HeatCurveLimitsError(ValueError):
    """Raised when the configured low and high limits conflict."""


@dataclass(frozen=True, slots=True)
class HeatCurveSettings:
    """Persistent user settings for heating-target control."""

    mode: HeatCurveMode = DEFAULT_HEAT_CURVE_MODE
    starting_point: float = DEFAULT_HEAT_CURVE_STARTING_POINT
    curve: float = DEFAULT_HEAT_CURVE_CURVE
    high_limit: float = DEFAULT_HEAT_CURVE_HIGH_LIMIT
    low_limit: float = DEFAULT_HEAT_CURVE_LOW_LIMIT
    prediction_horizon: int = DEFAULT_PREDICTION_HORIZON
    indoor_target: float = DEFAULT_INDOOR_TARGET

    @property
    def enabled(self) -> bool:
        """Return whether any automatic mode is selected."""
        return self.mode is not HeatCurveMode.MANUAL

    @classmethod
    def from_dict(cls, stored: dict[str, Any] | None) -> HeatCurveSettings:
        """Load settings and migrate the v0.4 enabled switch safely."""
        if not isinstance(stored, dict) or not stored:
            return cls()
        try:
            raw_mode = stored.get("mode")
            if raw_mode is None:
                mode = HeatCurveMode.AMBIENT if stored.get("enabled") is True else HeatCurveMode.MANUAL
            else:
                mode = HeatCurveMode(raw_mode)
            settings = cls(
                mode=mode,
                starting_point=float(stored.get("starting_point", DEFAULT_HEAT_CURVE_STARTING_POINT)),
                curve=round(float(stored.get("curve", DEFAULT_HEAT_CURVE_CURVE)), 2),
                high_limit=float(stored.get("high_limit", DEFAULT_HEAT_CURVE_HIGH_LIMIT)),
                low_limit=float(stored.get("low_limit", DEFAULT_HEAT_CURVE_LOW_LIMIT)),
                prediction_horizon=int(stored.get("prediction_horizon", DEFAULT_PREDICTION_HORIZON)),
                indoor_target=float(stored.get("indoor_target", DEFAULT_INDOOR_TARGET)),
            )
            settings.validate()
        except (TypeError, ValueError):
            return cls()
        return settings

    def as_dict(self) -> dict[str, str | float | int]:
        """Return JSON-serializable settings."""
        return {
            "mode": self.mode.value,
            "starting_point": self.starting_point,
            "curve": self.curve,
            "high_limit": self.high_limit,
            "low_limit": self.low_limit,
            "prediction_horizon": self.prediction_horizon,
            "indoor_target": self.indoor_target,
        }

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
        if not PREDICTION_HORIZON_MIN <= self.prediction_horizon <= PREDICTION_HORIZON_MAX:
            raise ValueError("Prediction horizon must be between 1 and 12 hours")
        if not isfinite(self.indoor_target) or not INDOOR_TARGET_MIN <= self.indoor_target <= INDOOR_TARGET_MAX:
            raise ValueError("Indoor target must be between 15 and 25 °C")

    def with_value(self, setting: HeatCurveSetting, value: str | float) -> HeatCurveSettings:
        """Return settings with one validated value changed."""
        if setting == "mode":
            updated = replace(self, mode=HeatCurveMode(value))
        else:
            numeric = float(value)
            if setting == "curve":
                if not isfinite(numeric) or not HEAT_CURVE_CURVE_MIN <= numeric <= HEAT_CURVE_CURVE_MAX:
                    raise ValueError("Heat-curve slope must be between 0 and 1")
                numeric = round(numeric, 2)
            if setting == "prediction_horizon":
                if not numeric.is_integer():
                    raise ValueError("Prediction horizon must use whole hours")
                updated = replace(self, prediction_horizon=int(numeric))
            else:
                updated = replace(self, **{setting: numeric})
        updated.validate()
        return updated


@dataclass(frozen=True, slots=True)
class HeatCurveCalculation:
    """Details of one bounded and step-aligned curve calculation."""

    raw_target: float
    target: float
    effective_low: float
    effective_high: float


@dataclass(frozen=True, slots=True)
class PredictiveTemperature:
    """Forecast-derived effective ambient temperature."""

    effective_temperature: float
    forecast_temperature: float
    target_time: datetime


def valid_temperature(value: Any) -> float | None:
    """Return a finite numeric temperature without accepting booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        return None
    return float(value)


def calculate_heat_curve(
    settings: HeatCurveSettings,
    ambient_temperature: float,
    *,
    indoor_correction: float = 0.0,
    step: float,
    step_origin: float = 0.0,
    target_minimum: float | None = None,
    target_maximum: float | None = None,
) -> HeatCurveCalculation | None:
    """Calculate, constrain, and step-align one heating target."""
    ambient = valid_temperature(ambient_temperature)
    if ambient is None or not isfinite(indoor_correction):
        return None
    effective_low = max(settings.low_limit, target_minimum) if target_minimum is not None else settings.low_limit
    effective_high = min(settings.high_limit, target_maximum) if target_maximum is not None else settings.high_limit
    if effective_low > effective_high:
        return None

    raw_target = ambient * -settings.curve + settings.starting_point + indoor_correction
    target = min(max(raw_target, effective_low), effective_high)
    if step > 0:
        aligned_low = ceil((effective_low - step_origin) / step - 1e-9) * step + step_origin
        aligned_high = floor((effective_high - step_origin) / step + 1e-9) * step + step_origin
        if aligned_low > aligned_high:
            return None
        target = round((target - step_origin) / step) * step + step_origin
        target = min(max(target, aligned_low), aligned_high)
    return HeatCurveCalculation(
        raw_target=round(raw_target, 4),
        target=round(target, 4),
        effective_low=round(effective_low, 4),
        effective_high=round(effective_high, 4),
    )


def heat_curve_target(
    settings: HeatCurveSettings,
    data: dict[str, Any],
    *,
    step: float,
    step_origin: float = 0.0,
    target_minimum: float | None = None,
    target_maximum: float | None = None,
) -> float | None:
    """Calculate an ambient-mode target, or return None when inactive."""
    if not settings.enabled:
        return None
    power = data.get("power_state") or data.get("power")
    if power != "on" or data.get("mode") != "heating":
        return None
    ambient = valid_temperature(data.get("ambient_temperature"))
    if ambient is None:
        return None
    calculation = calculate_heat_curve(
        settings,
        ambient,
        step=step,
        step_origin=step_origin,
        target_minimum=target_minimum,
        target_maximum=target_maximum,
    )
    return calculation.target if calculation else None


def indoor_temperature_correction(settings: HeatCurveSettings, indoor_temperature: Any) -> float | None:
    """Return a deliberately slow and bounded water-target correction."""
    indoor = valid_temperature(indoor_temperature)
    if indoor is None:
        return None
    correction = (settings.indoor_target - indoor) * INDOOR_CORRECTION_FACTOR
    return round(min(max(correction, -INDOOR_CORRECTION_LIMIT), INDOOR_CORRECTION_LIMIT), 2)


def _interpolate_temperature(
    points: list[tuple[datetime, float]], target_time: datetime
) -> float | None:
    """Interpolate a temperature at an exact forecast time."""
    before: tuple[datetime, float] | None = None
    after: tuple[datetime, float] | None = None
    for point in points:
        if point[0] <= target_time:
            before = point
        if point[0] >= target_time:
            after = point
            break
    if before and before[0] == target_time:
        return before[1]
    if before is None or after is None:
        return None
    duration = (after[0] - before[0]).total_seconds()
    if duration <= 0:
        return None
    fraction = (target_time - before[0]).total_seconds() / duration
    return before[1] + (after[1] - before[1]) * fraction


def predictive_temperature(
    ambient_temperature: Any,
    forecast_points: list[tuple[datetime, float]],
    *,
    now: datetime,
    horizon_hours: int,
) -> PredictiveTemperature | None:
    """Return the time-weighted outdoor temperature until the prediction horizon."""
    if now.tzinfo is None:
        raise ValueError("Prediction time must be timezone-aware")
    points = sorted(
        (
            (timestamp, float(value))
            for timestamp, value in forecast_points
            if timestamp.tzinfo is not None and valid_temperature(value) is not None
        ),
        key=lambda point: point[0],
    )
    target_time = now + timedelta(hours=horizon_hours)
    endpoint = _interpolate_temperature(points, target_time)
    if endpoint is None:
        return None
    start = valid_temperature(ambient_temperature)
    if start is None:
        start = _interpolate_temperature(points, now)
    if start is None:
        return None

    path = [(now, start)]
    path.extend(point for point in points if now < point[0] < target_time)
    path.append((target_time, endpoint))
    weighted_sum = 0.0
    total_seconds = 0.0
    for (left_time, left_temp), (right_time, right_temp) in pairwise(path):
        seconds = (right_time - left_time).total_seconds()
        if seconds <= 0:
            continue
        weighted_sum += ((left_temp + right_temp) / 2) * seconds
        total_seconds += seconds
    if total_seconds <= 0:
        return None
    return PredictiveTemperature(
        effective_temperature=round(weighted_sum / total_seconds, 2),
        forecast_temperature=round(endpoint, 2),
        target_time=target_time,
    )


def heat_curve_target_needs_write(current_target: Any, calculated_target: float | None) -> bool:
    """Return whether an active calculated target differs from controller state."""
    if calculated_target is None:
        return False
    if isinstance(current_target, bool) or not isinstance(current_target, (int, float)):
        return True
    return abs(float(current_target) - calculated_target) >= 1e-6
