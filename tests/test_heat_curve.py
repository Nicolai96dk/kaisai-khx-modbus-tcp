"""Heat-curve calculation and validation tests."""

import pytest

from custom_components.kaisai_khx.heat_curve import (
    HeatCurveSettings,
    heat_curve_target,
    heat_curve_target_needs_write,
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

    settings = defaults.with_value("enabled", True)

    assert heat_curve_target(settings, active_data(0), step=0.5) == 30.0
    assert heat_curve_target(settings, active_data(-10), step=0.5) == 34.0
    assert heat_curve_target(settings, active_data(10), step=0.5) == 26.0


def test_heat_curve_is_bounded_and_rounded_to_profile_step() -> None:
    settings = HeatCurveSettings(enabled=True)

    assert heat_curve_target(settings, active_data(-30), step=0.5) == 35.0
    assert heat_curve_target(settings, active_data(40), step=0.5) == 20.0
    assert heat_curve_target(settings, active_data(11), step=0.5) == 25.5


def test_heat_curve_limits_stay_safe_with_a_different_profile_step() -> None:
    settings = HeatCurveSettings(enabled=True, low_limit=20.5, high_limit=35.5)

    assert heat_curve_target(settings, active_data(-30), step=1.0) == 35.0
    assert heat_curve_target(settings, active_data(40), step=1.0) == 21.0


def test_heat_curve_also_obeys_active_profile_limits() -> None:
    settings = HeatCurveSettings(enabled=True, low_limit=10, high_limit=50)

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
    assert heat_curve_target(HeatCurveSettings(enabled=True), data, step=0.5) is None


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
    ],
)
def test_heat_curve_rejects_values_outside_safety_ranges(setting, value) -> None:
    with pytest.raises(ValueError):
        HeatCurveSettings().with_value(setting, value)


def test_invalid_stored_settings_fall_back_to_safe_defaults() -> None:
    assert HeatCurveSettings.from_dict({"enabled": True, "low_limit": 45, "high_limit": 20}) == HeatCurveSettings()
    assert HeatCurveSettings.from_dict(["invalid"]) == HeatCurveSettings()


def test_curve_is_stored_with_two_decimal_precision() -> None:
    assert HeatCurveSettings().with_value("curve", 0.405).curve == 0.41


def test_heat_curve_writes_only_for_a_changed_active_target() -> None:
    assert not heat_curve_target_needs_write(30.0, None)
    assert not heat_curve_target_needs_write(30.0, 30.0)
    assert heat_curve_target_needs_write(29.5, 30.0)
    assert heat_curve_target_needs_write(None, 30.0)
