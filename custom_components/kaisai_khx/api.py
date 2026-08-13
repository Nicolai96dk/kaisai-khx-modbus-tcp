"""Backend-neutral KAISAI KHX device API."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from modbus_connection import ModbusUnit

from .profile import (
    INTEGRATION_WRITE_LIMITS,
    SEMANTIC_WRITE_ALLOWLIST,
    DataType,
    RegisterDefinition,
    RegisterProfile,
    RegisterType,
)

POWER_STATE_VERIFY_ATTEMPTS = 6
POWER_STATE_VERIFY_DELAY = 1.0


@dataclass(frozen=True, slots=True)
class ReadBlock:
    register_type: RegisterType
    start: int
    count: int
    keys: tuple[str, ...]


def plan_reads(
    profile: RegisterProfile,
    register_keys: set[str] | None = None,
    *,
    max_gap: int = 2,
    max_count: int = 16,
) -> list[ReadBlock]:
    """Group nearby compatible one-word registers into conservative blocks."""
    blocks: list[ReadBlock] = []
    for register_type in RegisterType:
        definitions = sorted(
            (
                register
                for register in profile.registers.values()
                if register.register_type == register_type and (register_keys is None or register.key in register_keys)
            ),
            key=lambda r: r.address,
        )
        current: list[RegisterDefinition] = []
        for definition in definitions:
            if current and (
                definition.address - current[-1].address > max_gap + 1
                or definition.address - current[0].address + 1 > max_count
            ):
                blocks.append(
                    ReadBlock(
                        register_type,
                        current[0].address,
                        current[-1].address - current[0].address + 1,
                        tuple(r.key for r in current),
                    )
                )
                current = []
            current.append(definition)
        if current:
            blocks.append(
                ReadBlock(
                    register_type,
                    current[0].address,
                    current[-1].address - current[0].address + 1,
                    tuple(r.key for r in current),
                )
            )
    return blocks


class KaisaiKhxDevice:
    """Protocol implementation consuming only ModbusUnit."""

    def __init__(self, unit: ModbusUnit, profile: RegisterProfile) -> None:
        self.unit = unit
        self.profile = profile

    async def read_all(self, register_keys: set[str] | None = None) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for block in plan_reads(self.profile, register_keys):
            try:
                raw_values = await self._read(block.register_type, block.start, block.count)
            except Exception:
                # A model may reject a block containing an optional hole. Fall back
                # per register so supported values stay available.
                for key in block.keys:
                    definition = self.profile.registers[key]
                    try:
                        raw = (await self._read(definition.register_type, definition.address, 1))[0]
                    except Exception:
                        if not definition.optional:
                            raise
                        values[key] = None
                    else:
                        values[key] = definition.decode(raw)
                continue
            for key in block.keys:
                definition = self.profile.registers[key]
                values[key] = definition.decode(raw_values[definition.address - block.start])
        return values

    async def _read(self, kind: RegisterType, address: int, count: int) -> list[int]:
        if kind == RegisterType.INPUT:
            return await self.unit.read_input_registers(address, count)
        return await self.unit.read_holding_registers(address, count)

    async def read_register(self, definition: RegisterDefinition) -> tuple[int, Any]:
        raw = (await self._read(definition.register_type, definition.address, 1))[0]
        return raw, definition.decode(raw)

    async def write(self, key: str, value: float | int) -> None:
        """Write one explicitly allowed semantic control and verify it."""
        if key not in SEMANTIC_WRITE_ALLOWLIST:
            raise ValueError(f"Writes are not permitted for semantic key {key}")
        definition = self.profile.registers[key]
        if definition.data_type == DataType.BITFIELD:
            raise ValueError(f"Bitfield writes are not permitted for {key}")
        if key in INTEGRATION_WRITE_LIMITS:
            lower, upper = INTEGRATION_WRITE_LIMITS[key]
            numeric = float(value)
            if not lower <= numeric <= upper:
                raise ValueError(f"Value for {key} is outside integration safety limits")
        if key == "power" and int(value) not in (0, 1):
            raise ValueError("Power must be 0 or 1")
        if key == "mode" and int(value) not in (0, 1, 2, 3, 4):
            raise ValueError("Operating mode is outside the supported allowlist")
        if key in ("power", "mode") and (not definition.enum or int(value) not in definition.enum):
            raise ValueError(f"Value for {key} is not present in the active profile enum")
        raw = definition.encode(value)
        await self.unit.write_register(definition.address, raw)
        confirmation = definition
        if key == self.profile.power_command_key and self.profile.power_state_key:
            candidate = self.profile.registers.get(self.profile.power_state_key)
            if candidate is not None:
                readback_available = False
                for attempt in range(POWER_STATE_VERIFY_ATTEMPTS):
                    try:
                        confirmed = (await self._read(candidate.register_type, candidate.address, 1))[0]
                    except Exception:
                        break
                    readback_available = True
                    if confirmed != raw:
                        if attempt < POWER_STATE_VERIFY_ATTEMPTS - 1:
                            await asyncio.sleep(POWER_STATE_VERIFY_DELAY)
                        continue
                    return
                if readback_available:
                    raise RuntimeError("Power-state readback did not match the command")
        confirmed = (await self._read(confirmation.register_type, confirmation.address, 1))[0]
        if confirmed != raw:
            raise RuntimeError(f"Write verification failed for {key}")
