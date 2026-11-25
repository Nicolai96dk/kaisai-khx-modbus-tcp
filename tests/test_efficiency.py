"""Regression tests for circulation and paired energy accumulation."""

from datetime import date, timedelta

import pytest

from custom_components.kaisai_khx.efficiency import (
    EfficiencyTracker,
    circulating_water,
    electrical_power_kw,
    heating_power_kw,
)
from custom_components.kaisai_khx.profile import BUILTIN_PROFILE, profile_for_capabilities

TODAY = date(2026, 11, 21)


def test_efficiency_reads_circulation_without_enabling_all_diagnostics() -> None:
    standard_profile = profile_for_capabilities(BUILTIN_PROFILE, dhw_enabled=False)
    assert not standard_profile.bits
    assert {"water_inlet_temperature", "water_outlet_temperature"} <= standard_profile.registers.keys()
    assert {"input_states", "output_states"}.isdisjoint(standard_profile.registers)

    profile = profile_for_capabilities(BUILTIN_PROFILE, dhw_enabled=False, efficiency_enabled=True)
    assert {bit.key for bit in profile.bits} == {"water_flow_switch", "main_circulating_water_pump"}
    assert circulating_water({"input_states": 0, "output_states": 16}, profile.bits) is True
    assert circulating_water({"input_states": 4, "output_states": 16}, profile.bits) is False
    assert circulating_water({"input_states": 0, "output_states": 0}, profile.bits) is False
    assert circulating_water({"output_states": 16}, profile.bits) is True
    assert circulating_water({}, profile.bits) is None


@pytest.mark.parametrize(
    ("power_sensor", "flow"),
    (
        (None, 1.0),
        ("", 1.0),
        ("sensor.", 1.0),
        ("switch.meter", 1.0),
        ("sensor.power", None),
        ("sensor.power", 0),
        ("sensor.power", float("nan")),
    ),
)
def test_incomplete_calibration_does_not_enable_efficiency(power_sensor: object, flow: object) -> None:
    assert EfficiencyTracker.from_calibration(power_sensor, flow) is None


def test_calibration_preserves_meter_and_flow() -> None:
    tracker = EfficiencyTracker.from_calibration("sensor.power", 0.78)

    assert tracker is not None
    assert tracker.power_sensor == "sensor.power"
    assert tracker.flow_m3h == 0.78


def test_heat_output_uses_configured_flow_and_preserves_defrost_loss() -> None:
    data = {"water_inlet_temperature": 25.1, "water_outlet_temperature": 28.1}
    assert heating_power_kw(data, 1.0, True) == pytest.approx(3.48)
    assert heating_power_kw(data, 1.0, False) == 0
    assert heating_power_kw(data, 1.0, None) is None
    assert heating_power_kw({"water_outlet_temperature": 28.1}, 1.0, True) is None
    assert heating_power_kw({**data, "water_outlet_temperature": 22.1}, 0.8, True) == pytest.approx(-2.784)
    assert electrical_power_kw("575", "W") == pytest.approx(0.575)
    assert electrical_power_kw("0.575", "kW") == pytest.approx(0.575)
    assert electrical_power_kw("575", "kWh") is None
    assert electrical_power_kw("unavailable", "W") is None


@pytest.mark.parametrize(
    ("mode", "circulating", "heat_kw", "power_kw", "cop"),
    (
        ("heating", True, 4.0, 1.0, 4.0),
        ("heating", False, 0.0, 0.1, None),
        ("heating", True, 0.0, 0.1, None),
        ("heating", None, None, 1.0, None),
        ("heating", True, 4.0, None, None),
        ("defrosting", True, -2.0, 1.0, None),
        ("cooling", True, -4.0, 1.0, None),
    ),
)
def test_cop_requires_valid_active_heating(
    mode: str,
    circulating: bool | None,
    heat_kw: float | None,
    power_kw: float | None,
    cop: float | None,
) -> None:
    tracker = EfficiencyTracker("sensor.power", 1.0)
    tracker.sample(
        0,
        day=TODAY,
        status=mode,
        circulating=circulating,
        heat_kw=heat_kw,
        power_kw=power_kw,
        max_gap_seconds=120,
    )

    assert tracker.cop == cop


def test_spf_includes_standby_and_defrost_and_skips_gaps() -> None:
    tracker = EfficiencyTracker("sensor.power", 1.0)
    tracker.sample(0, day=TODAY, status="heating", circulating=True, heat_kw=4, power_kw=1, max_gap_seconds=120)
    assert tracker.cop == 4
    assert tracker.spf is None
    tracker.sample(60, day=TODAY, status="defrosting", circulating=True, heat_kw=-2, power_kw=1, max_gap_seconds=120)
    assert tracker.cop is None
    tracker.sample(120, day=TODAY, status="heating", circulating=False, heat_kw=0, power_kw=0.2, max_gap_seconds=120)
    assert tracker.cop is None
    assert tracker.totals.heat_kwh == pytest.approx(0)
    assert tracker.totals.electricity_kwh == pytest.approx(1.6 / 60)
    before_gap = tracker.as_dict()

    tracker.sample(1000, day=TODAY, status="heating", circulating=True, heat_kw=4, power_kw=1, max_gap_seconds=120)
    tracker.sample(1060, day=TODAY, status="heating", circulating=True, heat_kw=4, power_kw=None, max_gap_seconds=120)
    tracker.sample(1120, day=TODAY, status="heating", circulating=True, heat_kw=4, power_kw=1, max_gap_seconds=120)
    tracker.sample(1180, day=TODAY, status="cooling", circulating=True, heat_kw=-4, power_kw=1, max_gap_seconds=120)
    tracker.sample(1240, day=TODAY, status="heating", circulating=True, heat_kw=4, power_kw=1, max_gap_seconds=120)
    assert tracker.as_dict() == before_gap


def test_spf_restores_same_calibration_and_expires_old_days() -> None:
    tracker = EfficiencyTracker("sensor.power", 1.0)
    tracker.sample(0, day=TODAY, status="heating", circulating=True, heat_kw=4, power_kw=1, max_gap_seconds=120)
    tracker.sample(60, day=TODAY, status="heating", circulating=True, heat_kw=4, power_kw=1, max_gap_seconds=120)
    stored = tracker.as_dict()

    restored = EfficiencyTracker("sensor.power", 1.0)
    restored.restore(stored, TODAY + timedelta(days=364))
    assert restored.spf == pytest.approx(4)
    restored.sample(
        0,
        day=TODAY + timedelta(days=365),
        status="heating",
        circulating=True,
        heat_kw=4,
        power_kw=1,
        max_gap_seconds=120,
    )
    assert restored.spf is None

    recalibrated = EfficiencyTracker("sensor.power", 0.8)
    recalibrated.restore(stored, TODAY)
    assert recalibrated.spf is None


def test_restore_ignores_last_cop_from_an_older_release() -> None:
    tracker = EfficiencyTracker("sensor.power", 1.0)
    tracker.restore(
        {
            "power_sensor": "sensor.power",
            "flow_m3h": 1.0,
            "last_cop": 4.14,
            "last_cop_at": "2026-11-21T12:00:00+00:00",
            "days": {TODAY.isoformat(): {"heat_kwh": 4.0, "electricity_kwh": 1.0, "observed_hours": 1.0}},
        },
        TODAY,
    )

    assert tracker.cop is None
    assert tracker.spf == 4.0
