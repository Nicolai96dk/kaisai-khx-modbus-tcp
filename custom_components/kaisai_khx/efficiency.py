"""Estimate heating efficiency from the KHX temperatures and an external meter."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from math import isfinite
from typing import Any

from .profile import CIRCULATION_BITS, BitDefinition

MIN_FLOW_M3H = 0.01
POWER_UNITS = {"W": 0.001, "kW": 1.0}
WATER_HEAT_CAPACITY_KWH_PER_M3_K = 1.16
HEATING_STATUSES = {"heating", "hot_water", "high_temperature_disinfection", "defrosting"}
EFFICIENCY_STORAGE_VERSION = 1
EFFICIENCY_CHECKPOINT_SECONDS = 300
SPF_WINDOW_DAYS = 365


def efficiency_storage_key(entry_id: str) -> str:
    return f"kaisai_khx.{entry_id}.efficiency"


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if isfinite(number) else None


def electrical_power_kw(state: str, unit: str | None) -> float | None:
    """Convert a nonnegative electrical power reading to kW."""
    power = _finite_number(state)
    factor = POWER_UNITS.get(unit) if unit is not None else None
    return power * factor if power is not None and power >= 0 and factor is not None else None


def circulating_water(data: Mapping[str, Any], bits: tuple[BitDefinition, ...]) -> bool | None:
    """Require each available indication of flow and preserve missing data."""
    states = [
        bit.decode(raw)
        for bit in bits
        if bit.key in CIRCULATION_BITS and isinstance(raw := data.get(bit.register), int)
    ]
    return all(states) if states else None


def heating_power_kw(data: Mapping[str, Any], flow_m3h: float, circulating: bool | None) -> float | None:
    """Estimate signed heat transfer using the configured flow of water."""
    if circulating is False:
        return 0.0
    inlet = _finite_number(data.get("water_inlet_temperature"))
    outlet = _finite_number(data.get("water_outlet_temperature"))
    if circulating is None or inlet is None or outlet is None:
        return None
    return _finite_number(WATER_HEAT_CAPACITY_KWH_PER_M3_K * flow_m3h * (outlet - inlet))


@dataclass(slots=True)
class EnergyTotals:
    """Paired thermal energy and electricity for observed intervals."""

    heat_kwh: float = 0.0
    electricity_kwh: float = 0.0
    observed_hours: float = 0.0


@dataclass(slots=True)
class EfficiencyTracker:
    """Accumulate heat and electricity over the same valid sample intervals."""

    power_sensor: str
    flow_m3h: float
    cop: float | None = field(init=False, default=None)
    _previous: tuple[float, float, float] | None = field(init=False, default=None)
    _days: dict[date, EnergyTotals] = field(init=False, default_factory=dict)
    _last_day: date | None = field(init=False, default=None)

    @property
    def totals(self) -> EnergyTotals:
        return EnergyTotals(
            heat_kwh=sum(day.heat_kwh for day in self._days.values()),
            electricity_kwh=sum(day.electricity_kwh for day in self._days.values()),
            observed_hours=sum(day.observed_hours for day in self._days.values()),
        )

    @property
    def spf(self) -> float | None:
        totals = self.totals
        return totals.heat_kwh / totals.electricity_kwh if totals.electricity_kwh > 0 else None

    def invalidate(self) -> None:
        self.cop = None
        self._previous = None

    def sample(
        self,
        now: float,
        *,
        day: date,
        status: str | None,
        circulating: bool | None,
        heat_kw: float | None,
        power_kw: float | None,
        max_gap_seconds: float,
    ) -> bool:
        """Record an instantaneous reading and return whether totals advanced."""
        self._advance_window(day)
        if status not in HEATING_STATUSES or circulating is None or heat_kw is None or power_kw is None:
            self.invalidate()
            return False

        self.cop = (
            heat_kw / power_kw if status != "defrosting" and circulating and heat_kw > 0 and power_kw > 0 else None
        )

        previous = self._previous
        self._previous = (now, heat_kw, power_kw)
        if previous is None:
            return False
        previous_time, previous_heat, previous_power = previous
        elapsed = now - previous_time
        if not 0 < elapsed <= max_gap_seconds:
            return False
        hours = elapsed / 3600
        totals = self._days.setdefault(day, EnergyTotals())
        totals.heat_kwh += (previous_heat + heat_kw) / 2 * hours
        totals.electricity_kwh += (previous_power + power_kw) / 2 * hours
        totals.observed_hours += hours
        return True

    def _advance_window(self, day: date) -> None:
        if day == self._last_day:
            return
        oldest = day - timedelta(days=SPF_WINDOW_DAYS - 1)
        self._days = {date_: values for date_, values in self._days.items() if oldest <= date_ <= day}
        self._last_day = day

    def restore(self, data: dict[str, Any] | None, day: date) -> None:
        """Resume totals for the same meter and flow calibration."""
        if not data or data.get("power_sensor") != self.power_sensor or data.get("flow_m3h") != self.flow_m3h:
            return
        for day_key, values in data.get("days", {}).items():
            self._days[date.fromisoformat(day_key)] = EnergyTotals(
                heat_kwh=values["heat_kwh"],
                electricity_kwh=values["electricity_kwh"],
                observed_hours=values["observed_hours"],
            )
        self._advance_window(day)

    def as_dict(self) -> dict[str, Any]:
        """Serialize totals without carrying samples across restarts."""
        return {
            "power_sensor": self.power_sensor,
            "flow_m3h": self.flow_m3h,
            "days": {
                day.isoformat(): {
                    "heat_kwh": totals.heat_kwh,
                    "electricity_kwh": totals.electricity_kwh,
                    "observed_hours": totals.observed_hours,
                }
                for day, totals in self._days.items()
            },
        }
