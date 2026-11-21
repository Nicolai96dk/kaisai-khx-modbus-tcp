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
    profile = profile_for_capabilities(BUILTIN_PROFILE, dhw_enabled=False, efficiency_enabled=True)
    assert {bit.key for bit in profile.bits} == {"water_flow_switch", "main_circulating_water_pump"}
    assert circulating_water({"input_states": 0, "output_states": 16}, profile.bits) is True
    assert circulating_water({"input_states": 4, "output_states": 16}, profile.bits) is False
    assert circulating_water({"input_states": 0, "output_states": 0}, profile.bits) is False
    assert circulating_water({"output_states": 16}, profile.bits) is True
    assert circulating_water({}, profile.bits) is None


def test_heat_output_uses_configured_flow_and_preserves_defrost_loss() -> None:
    data = {"water_inlet_temperature": 25.1, "water_outlet_temperature": 28.1}
    assert heating_power_kw(data, 1.0, True) == pytest.approx(3.48)
    assert heating_power_kw(data, 1.0, False) == 0
    assert heating_power_kw(data, 1.0, None) is None
    assert heating_power_kw({**data, "water_outlet_temperature": 22.1}, 0.8, True) == pytest.approx(-2.784)
    assert electrical_power_kw("575", "W") == pytest.approx(0.575)
    assert electrical_power_kw("0.575", "kW") == pytest.approx(0.575)
    assert electrical_power_kw("575", "kWh") is None
    assert electrical_power_kw("unavailable", "W") is None


def test_spf_includes_standby_and_defrost_and_skips_gaps() -> None:
    tracker = EfficiencyTracker("sensor.power", 1.0)
    tracker.sample(0, day=TODAY, status="heating", heat_kw=4, power_kw=1, max_gap_seconds=120)
    assert tracker.cop == 4
    assert tracker.spf is None
    tracker.sample(60, day=TODAY, status="defrosting", heat_kw=-2, power_kw=1, max_gap_seconds=120)
    assert tracker.cop is None
    tracker.sample(120, day=TODAY, status="heating", heat_kw=0, power_kw=0.2, max_gap_seconds=120)
    assert tracker.cop is None
    assert tracker.totals.heat_kwh == pytest.approx(0)
    assert tracker.totals.electricity_kwh == pytest.approx(1.6 / 60)
    before_gap = tracker.as_dict()

    tracker.sample(1000, day=TODAY, status="heating", heat_kw=4, power_kw=1, max_gap_seconds=120)
    tracker.sample(1060, day=TODAY, status="heating", heat_kw=4, power_kw=None, max_gap_seconds=120)
    tracker.sample(1120, day=TODAY, status="heating", heat_kw=4, power_kw=1, max_gap_seconds=120)
    tracker.sample(1180, day=TODAY, status="cooling", heat_kw=-4, power_kw=1, max_gap_seconds=120)
    tracker.sample(1240, day=TODAY, status="heating", heat_kw=4, power_kw=1, max_gap_seconds=120)
    assert tracker.as_dict() == before_gap


def test_spf_restores_same_calibration_and_expires_old_days() -> None:
    tracker = EfficiencyTracker("sensor.power", 1.0)
    tracker.sample(0, day=TODAY, status="heating", heat_kw=4, power_kw=1, max_gap_seconds=120)
    tracker.sample(60, day=TODAY, status="heating", heat_kw=4, power_kw=1, max_gap_seconds=120)
    stored = tracker.as_dict()

    restored = EfficiencyTracker("sensor.power", 1.0)
    restored.restore(stored, TODAY + timedelta(days=364))
    assert restored.spf == pytest.approx(4)
    restored.sample(0, day=TODAY + timedelta(days=365), status="heating", heat_kw=4, power_kw=1, max_gap_seconds=120)
    assert restored.spf is None

    recalibrated = EfficiencyTracker("sensor.power", 0.8)
    recalibrated.restore(stored, TODAY)
    assert recalibrated.spf is None
