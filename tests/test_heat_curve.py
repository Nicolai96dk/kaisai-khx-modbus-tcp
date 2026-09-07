"""Heat-curve calculation and validation tests."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.kaisai_khx.heat_curve import (
    HeatCurveMode,
    HeatCurveSettings,
    heat_curve_target,
    heat_curve_target_needs_write,
    indoor_temperature_correction,
    predictive_temperature,
)


def active_data(ambient: float) -> dict[str, object]:
    return {
        "power_state": "on",
        "power": "on",
        "mode": "heating",
        "ambient_temperature": ambient,
    }


def test_heat_curve_defaults_and_formula() -> None:
    defaults = HeatCurveSettings()
    assert defaults.enabled is False
    assert defaults.starting_point == 30.0
    assert defaults.curve == 0.4
    assert defaults.high_limit == 35.0
    assert defaults.low_limit == 20.0

    settings = defaults.with_value("mode", HeatCurveMode.AMBIENT)

    assert heat_curve_target(settings, active_data(0), step=0.5) == 30.0
    assert heat_curve_target(settings, active_data(-10), step=0.5) == 34.0
    assert heat_curve_target(settings, active_data(10), step=0.5) == 26.0


def test_heat_curve_is_bounded_and_rounded_to_profile_step() -> None:
    settings = HeatCurveSettings(mode=HeatCurveMode.AMBIENT)

    assert heat_curve_target(settings, active_data(-30), step=0.5) == 35.0
    assert heat_curve_target(settings, active_data(40), step=0.5) == 20.0
    assert heat_curve_target(settings, active_data(11), step=0.5) == 25.5


def test_heat_curve_limits_stay_safe_with_a_different_profile_step() -> None:
    settings = HeatCurveSettings(mode=HeatCurveMode.AMBIENT, low_limit=20.5, high_limit=35.5)

    assert heat_curve_target(settings, active_data(-30), step=1.0) == 35.0
    assert heat_curve_target(settings, active_data(40), step=1.0) == 21.0


def test_heat_curve_also_obeys_active_profile_limits() -> None:
    settings = HeatCurveSettings(mode=HeatCurveMode.AMBIENT, low_limit=10, high_limit=50)

    assert heat_curve_target(settings, active_data(-100), step=0.5, target_maximum=45) == 45.0
    assert heat_curve_target(settings, active_data(100), step=0.5, target_minimum=15) == 15.0


@pytest.mark.parametrize(
    "data",
    [
        active_data(0) | {"power_state": "off"},
        active_data(0) | {"mode": "cooling"},
        active_data(0) | {"mode": "hot_water_heating"},
        active_data(0) | {"ambient_temperature": None},
    ],
)
def test_heat_curve_only_runs_when_powered_on_in_heating_mode(data: dict[str, object]) -> None:
    assert heat_curve_target(HeatCurveSettings(mode=HeatCurveMode.AMBIENT), data, step=0.5) is None


def test_disabled_heat_curve_does_not_calculate() -> None:
    assert heat_curve_target(HeatCurveSettings(), active_data(0), step=0.5) is None


def test_heat_curve_rejects_invalid_limits() -> None:
    with pytest.raises(ValueError, match="low limit"):
        HeatCurveSettings().with_value("low_limit", 40)
    with pytest.raises(ValueError, match="low limit"):
        HeatCurveSettings().with_value("high_limit", 15)


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("starting_point", 9.5),
        ("starting_point", 50.5),
        ("curve", -0.01),
        ("curve", 1.01),
        ("high_limit", float("nan")),
        ("prediction_horizon", 0),
        ("prediction_horizon", 13),
        ("prediction_horizon", 8.5),
        ("indoor_target", 14.9),
        ("indoor_target", 25.1),
    ],
)
def test_heat_curve_rejects_values_outside_safety_ranges(setting, value) -> None:
    with pytest.raises(ValueError):
        HeatCurveSettings().with_value(setting, value)


def test_invalid_stored_settings_fall_back_to_safe_defaults() -> None:
    assert HeatCurveSettings.from_dict({"enabled": True, "low_limit": 45, "high_limit": 20}) == HeatCurveSettings()
    assert HeatCurveSettings.from_dict(["invalid"]) == HeatCurveSettings()


def test_v04_enabled_switch_migrates_to_an_exclusive_mode() -> None:
    enabled = HeatCurveSettings.from_dict({"enabled": True, "curve": 0.55})
    disabled = HeatCurveSettings.from_dict({"enabled": False, "curve": 0.55})

    assert enabled.mode is HeatCurveMode.AMBIENT
    assert enabled.curve == 0.55
    assert disabled.mode is HeatCurveMode.MANUAL
    assert "enabled" not in enabled.as_dict()


def test_predictive_temperature_uses_time_weighted_forecast_path() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    points = [(now + timedelta(hours=hour), 10 - 2 * hour) for hour in range(9)]

    prediction = predictive_temperature(10, points, now=now, horizon_hours=8)

    assert prediction is not None
    assert prediction.forecast_temperature == -6
    assert prediction.effective_temperature == 2
    assert prediction.target_time == now + timedelta(hours=8)


def test_predictive_temperature_interpolates_exact_horizon() -> None:
    now = datetime(2026, 1, 1, 0, 30, tzinfo=UTC)
    points = [
        (datetime(2026, 1, 1, hour, tzinfo=UTC), float(hour))
        for hour in range(13)
    ]

    prediction = predictive_temperature(0.5, points, now=now, horizon_hours=8)

    assert prediction is not None
    assert prediction.forecast_temperature == 8.5


def test_indoor_correction_is_slow_and_bounded() -> None:
    settings = HeatCurveSettings(indoor_target=21)

    assert indoor_temperature_correction(settings, 20.5) == 0.5
    assert indoor_temperature_correction(settings, 10) == 2
    assert indoor_temperature_correction(settings, 30) == -2
    assert indoor_temperature_correction(settings, None) is None


def test_curve_is_stored_with_two_decimal_precision() -> None:
    assert HeatCurveSettings().with_value("curve", 0.405).curve == 0.41


def test_heat_curve_writes_only_for_a_changed_active_target() -> None:
    assert not heat_curve_target_needs_write(30.0, None)
    assert not heat_curve_target_needs_write(30.0, 30.0)
    assert heat_curve_target_needs_write(29.5, 30.0)
    assert heat_curve_target_needs_write(None, 30.0)
