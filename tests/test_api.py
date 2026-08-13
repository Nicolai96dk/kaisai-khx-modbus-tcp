"""Device API planning, fallback, and write verification tests."""

from dataclasses import replace
from types import MappingProxyType

import pytest

from custom_components.kaisai_khx.api import KaisaiKhxDevice, plan_reads
from custom_components.kaisai_khx.profile import BUILTIN_PROFILE, profile_with_overrides


class FakeUnit:
    def __init__(self):
        self.values = {
            1011: 1,
            1012: 1,
            1157: 450,
            1158: 300,
            1159: 180,
            2012: 1,
            2013: 250,
            2014: 240,
            2019: 1,
            2034: 0,
            2045: 280,
            2046: 300,
            2047: 450,
            2048: 100,
            2072: 50,
            2074: 2,
            2075: 3,
        }
        self.writes = []

    async def read_holding_registers(self, address, count):
        return [self.values.get(address + i, 0) for i in range(count)]

    async def read_input_registers(self, address, count):
        return await self.read_holding_registers(address, count)

    async def write_register(self, address, value):
        self.values[address] = value
        self.writes.append((address, value))


def test_read_planner_groups_nearby_ranges() -> None:
    blocks = plan_reads(BUILTIN_PROFILE)
    assert any(block.start == 2045 and block.count == 4 for block in blocks)
    assert any(block.start == 2072 and block.count == 4 for block in blocks)
    assert all(block.count <= 16 for block in blocks)


def test_read_planner_can_plan_only_due_registers() -> None:
    blocks = plan_reads(
        BUILTIN_PROFILE,
        {"water_inlet_temperature", "water_outlet_temperature"},
    )
    assert len(blocks) == 1
    assert blocks[0].start == 2045
    assert blocks[0].count == 2


@pytest.mark.asyncio
async def test_read_and_verified_write() -> None:
    unit = FakeUnit()
    device = KaisaiKhxDevice(unit, BUILTIN_PROFILE)
    data = await device.read_all()
    assert data["water_outlet_temperature"] == 30.0
    assert data["operation_status"] == "heating"
    await device.write("heating_target_temperature", 31.5)
    assert unit.writes[-1] == (1158, 315)


@pytest.mark.asyncio
async def test_rejects_read_only_write() -> None:
    with pytest.raises(ValueError):
        await KaisaiKhxDevice(FakeUnit(), BUILTIN_PROFILE).write("ambient_temperature", 20)


@pytest.mark.asyncio
async def test_reads_selected_registers_only() -> None:
    data = await KaisaiKhxDevice(FakeUnit(), BUILTIN_PROFILE).read_all({"water_outlet_temperature"})
    assert data == {"water_outlet_temperature": 30.0}


class PowerReadbackUnit(FakeUnit):
    def __init__(self, *, actual_available=True, mismatch=False):
        super().__init__()
        self.actual_available = actual_available
        self.mismatch = mismatch
        self.values[2011] = 0

    async def read_holding_registers(self, address, count):
        if address == 2011 and not self.actual_available:
            raise RuntimeError("unsupported register")
        return await super().read_holding_registers(address, count)

    async def write_register(self, address, value):
        await super().write_register(address, value)
        if address == 1011 and self.actual_available and not self.mismatch:
            self.values[2011] = value


@pytest.mark.asyncio
async def test_power_write_uses_actual_state_when_available() -> None:
    unit = PowerReadbackUnit()
    await KaisaiKhxDevice(unit, BUILTIN_PROFILE).write("power", 1)
    assert unit.writes == [(1011, 1)]


@pytest.mark.asyncio
async def test_power_write_falls_back_to_command_register() -> None:
    unit = PowerReadbackUnit(actual_available=False)
    await KaisaiKhxDevice(unit, BUILTIN_PROFILE).write("power", 1)
    assert unit.values[1011] == 1


@pytest.mark.asyncio
async def test_power_write_fails_on_actual_state_mismatch() -> None:
    with pytest.raises(RuntimeError, match="did not match"):
        await KaisaiKhxDevice(PowerReadbackUnit(mismatch=True), BUILTIN_PROFILE).write("power", 1)


@pytest.mark.asyncio
async def test_semantic_write_allowlist_blocks_arbitrary_registers() -> None:
    custom = profile_with_overrides({"ambient_temperature": {"address": 4000}})
    with pytest.raises(ValueError, match="not permitted"):
        await KaisaiKhxDevice(FakeUnit(), custom).write("ambient_temperature", 20)


@pytest.mark.asyncio
async def test_integration_safety_limit_overrides_custom_temperature_range() -> None:
    registers = dict(BUILTIN_PROFILE.registers)
    registers["heating_target_temperature"] = replace(registers["heating_target_temperature"], maximum=100)
    unsafe_profile_object = replace(BUILTIN_PROFILE, registers=MappingProxyType(registers))
    with pytest.raises(ValueError, match="safety limits"):
        await KaisaiKhxDevice(FakeUnit(), unsafe_profile_object).write("heating_target_temperature", 61)


class MissingFaultRegistersUnit(FakeUnit):
    async def read_holding_registers(self, address, count):
        fault_addresses = {2081, 2082, 2083, 2085, 2086, 2087, 2088, 2089, 2090}
        if any(candidate in fault_addresses for candidate in range(address, address + count)):
            raise RuntimeError("fault block unsupported")
        return await super().read_holding_registers(address, count)


@pytest.mark.asyncio
async def test_optional_fault_block_failure_does_not_break_core_poll() -> None:
    data = await KaisaiKhxDevice(MissingFaultRegistersUnit(), BUILTIN_PROFILE).read_all()
    assert data["water_outlet_temperature"] == 30.0
    assert all(data[f"fault_{address}"] is None for address in (2081, 2082, 2083, 2085, 2086, 2087, 2088, 2089, 2090))
