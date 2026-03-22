"""SmartMeter Modbus — register definitions and Modbus/TCP client."""
from __future__ import annotations

import asyncio
import logging
import struct
from dataclasses import dataclass, field
from enum import Enum

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

_LOGGER = logging.getLogger(__name__)


class MeterModel(str, Enum):
    DDSU666 = "DDSU-666"   # Single-phase
    DTSU666 = "DTSU-666"   # Three-phase


@dataclass
class RegisterDefinition:
    """Definition of a single Modbus register (or register pair)."""
    address: int
    count: int            # number of 16-bit registers to read
    name: str
    unit: str | None
    device_class: str | None
    state_class: str | None
    scale: float          # raw value * scale = engineering value
    models: list[MeterModel] = field(default_factory=list)  # empty = all models


# ---------------------------------------------------------------------------
# Register map
# Chint DDSU-666 / DTSU-666 Modbus RTU register map (function code 0x03).
# All registers are 32-bit IEEE 754 float values stored in two consecutive
# 16-bit Modbus registers (big-endian word order, big-endian byte order).
# ---------------------------------------------------------------------------
REGISTER_DEFINITIONS: list[RegisterDefinition] = [
    # ===========================================================
    # DDSU-666 (single-phase) register map
    # Source: Chint DDSU666 User Manual ZTY0.464.1413, Appendix A
    # All measurements are 32-bit IEEE-754 float, 2 x 16-bit registers
    # ===========================================================

    # --- Voltage --- 0x2000
    RegisterDefinition(
        address=0x2000, count=2,
        name="voltage_l1", unit="V",
        device_class="voltage", state_class="measurement",
        scale=1.0,
        models=[MeterModel.DDSU666],
    ),

    # --- Current --- 0x2002
    RegisterDefinition(
        address=0x2002, count=2,
        name="current_l1", unit="A",
        device_class="current", state_class="measurement",
        scale=1.0,
        models=[MeterModel.DDSU666],
    ),

    # --- Active Power --- 0x2004  (unit: kW in register, exposed as W)
    RegisterDefinition(
        address=0x2004, count=2,
        name="active_power_total", unit="W",
        device_class="power", state_class="measurement",
        scale=1000.0,
        models=[MeterModel.DDSU666],
    ),

    # --- Reactive Power --- 0x2006  (unit: kvar in register, exposed as var)
    RegisterDefinition(
        address=0x2006, count=2,
        name="reactive_power_total", unit="var",
        device_class="reactive_power", state_class="measurement",
        scale=1000.0,
        models=[MeterModel.DDSU666],
    ),

    # --- Power Factor --- 0x200A
    RegisterDefinition(
        address=0x200A, count=2,
        name="power_factor_total", unit=None,
        device_class="power_factor", state_class="measurement",
        scale=1.0,
        models=[MeterModel.DDSU666],
    ),

    # --- Frequency --- 0x200E
    RegisterDefinition(
        address=0x200E, count=2,
        name="frequency", unit="Hz",
        device_class="frequency", state_class="measurement",
        scale=1.0,
        models=[MeterModel.DDSU666],
    ),

    # --- Energy Import --- 0x4000
    RegisterDefinition(
        address=0x4000, count=2,
        name="energy_import_total", unit="kWh",
        device_class="energy", state_class="total_increasing",
        scale=1.0,
        models=[MeterModel.DDSU666],
    ),

    # Note: The DDSU-666 manual lists 0x400A as reverse/export energy (-Ep),
    # but in practice the Elwin TCP gateway (and likely the meter itself) echoes
    # the import register value back for this address. Since single-phase load
    # meters do not export, this register is omitted for DDSU-666.

    # ===========================================================
    # DTSU-666 (three-phase) register map
    # Source: Chint DTSU666 User Manual ZTY0.464.1267, Table 10
    #
    # All values are IEEE-754 float32 (2 x 16-bit registers, big-endian ABCD).
    # The meter stores values at a reduced scale; the scale factor converts to
    # standard SI units:
    #   Voltage: raw × 0.1 → V
    #   Current: raw × 0.001 → A
    #   Power:   raw × 0.1 → W / var
    #   PF:      raw × 0.001 → dimensionless
    #   Freq:    raw × 0.01 → Hz
    #   Energy:  raw × 1.0 → kWh (stored already in kWh)
    # ===========================================================

    # --- Line voltages (Uab, Ubc, Uca) ---
    RegisterDefinition(
        address=0x2000, count=2,
        name="voltage_l1_l2", unit="V",
        device_class="voltage", state_class="measurement",
        scale=0.1,
        models=[MeterModel.DTSU666],
    ),
    RegisterDefinition(
        address=0x2002, count=2,
        name="voltage_l2_l3", unit="V",
        device_class="voltage", state_class="measurement",
        scale=0.1,
        models=[MeterModel.DTSU666],
    ),
    RegisterDefinition(
        address=0x2004, count=2,
        name="voltage_l3_l1", unit="V",
        device_class="voltage", state_class="measurement",
        scale=0.1,
        models=[MeterModel.DTSU666],
    ),

    # --- Phase voltages (Ua, Ub, Uc) ---
    RegisterDefinition(
        address=0x2006, count=2,
        name="voltage_l1", unit="V",
        device_class="voltage", state_class="measurement",
        scale=0.1,
        models=[MeterModel.DTSU666],
    ),
    RegisterDefinition(
        address=0x2008, count=2,
        name="voltage_l2", unit="V",
        device_class="voltage", state_class="measurement",
        scale=0.1,
        models=[MeterModel.DTSU666],
    ),
    RegisterDefinition(
        address=0x200A, count=2,
        name="voltage_l3", unit="V",
        device_class="voltage", state_class="measurement",
        scale=0.1,
        models=[MeterModel.DTSU666],
    ),

    # --- Current (Ia, Ib, Ic) ---
    RegisterDefinition(
        address=0x200C, count=2,
        name="current_l1", unit="A",
        device_class="current", state_class="measurement",
        scale=0.001,
        models=[MeterModel.DTSU666],
    ),
    RegisterDefinition(
        address=0x200E, count=2,
        name="current_l2", unit="A",
        device_class="current", state_class="measurement",
        scale=0.001,
        models=[MeterModel.DTSU666],
    ),
    RegisterDefinition(
        address=0x2010, count=2,
        name="current_l3", unit="A",
        device_class="current", state_class="measurement",
        scale=0.001,
        models=[MeterModel.DTSU666],
    ),

    # --- Active power (Pt total, Pa, Pb, Pc) ---
    RegisterDefinition(
        address=0x2012, count=2,
        name="active_power_total", unit="W",
        device_class="power", state_class="measurement",
        scale=0.1,
        models=[MeterModel.DTSU666],
    ),
    RegisterDefinition(
        address=0x2014, count=2,
        name="active_power_l1", unit="W",
        device_class="power", state_class="measurement",
        scale=0.1,
        models=[MeterModel.DTSU666],
    ),
    RegisterDefinition(
        address=0x2016, count=2,
        name="active_power_l2", unit="W",
        device_class="power", state_class="measurement",
        scale=0.1,
        models=[MeterModel.DTSU666],
    ),
    RegisterDefinition(
        address=0x2018, count=2,
        name="active_power_l3", unit="W",
        device_class="power", state_class="measurement",
        scale=0.1,
        models=[MeterModel.DTSU666],
    ),

    # --- Reactive power (Qt total, Qa, Qb, Qc) ---
    RegisterDefinition(
        address=0x201A, count=2,
        name="reactive_power_total", unit="var",
        device_class="reactive_power", state_class="measurement",
        scale=0.1,
        models=[MeterModel.DTSU666],
    ),
    RegisterDefinition(
        address=0x201C, count=2,
        name="reactive_power_l1", unit="var",
        device_class="reactive_power", state_class="measurement",
        scale=0.1,
        models=[MeterModel.DTSU666],
    ),
    RegisterDefinition(
        address=0x201E, count=2,
        name="reactive_power_l2", unit="var",
        device_class="reactive_power", state_class="measurement",
        scale=0.1,
        models=[MeterModel.DTSU666],
    ),
    RegisterDefinition(
        address=0x2020, count=2,
        name="reactive_power_l3", unit="var",
        device_class="reactive_power", state_class="measurement",
        scale=0.1,
        models=[MeterModel.DTSU666],
    ),

    # --- Power factor (PFt, PFa, PFb, PFc) ---
    RegisterDefinition(
        address=0x202A, count=2,
        name="power_factor_total", unit=None,
        device_class="power_factor", state_class="measurement",
        scale=0.001,
        models=[MeterModel.DTSU666],
    ),
    RegisterDefinition(
        address=0x202C, count=2,
        name="power_factor_l1", unit=None,
        device_class="power_factor", state_class="measurement",
        scale=0.001,
        models=[MeterModel.DTSU666],
    ),
    RegisterDefinition(
        address=0x202E, count=2,
        name="power_factor_l2", unit=None,
        device_class="power_factor", state_class="measurement",
        scale=0.001,
        models=[MeterModel.DTSU666],
    ),
    RegisterDefinition(
        address=0x2030, count=2,
        name="power_factor_l3", unit=None,
        device_class="power_factor", state_class="measurement",
        scale=0.001,
        models=[MeterModel.DTSU666],
    ),

    # --- Frequency ---
    RegisterDefinition(
        address=0x2044, count=2,
        name="frequency", unit="Hz",
        device_class="frequency", state_class="measurement",
        scale=0.01,
        models=[MeterModel.DTSU666],
    ),

    # --- Energy import / export ---
    RegisterDefinition(
        address=0x101E, count=2,
        name="energy_import_total", unit="kWh",
        device_class="energy", state_class="total_increasing",
        scale=1.0,
        models=[MeterModel.DTSU666],
    ),
    RegisterDefinition(
        address=0x1028, count=2,
        name="energy_export_total", unit="kWh",
        device_class="energy", state_class="total_increasing",
        scale=1.0,
        models=[MeterModel.DTSU666],
    ),
]


def registers_for_model(model: MeterModel) -> list[RegisterDefinition]:
    """Return only registers applicable to the given meter model."""
    return [r for r in REGISTER_DEFINITIONS if not r.models or model in r.models]


# ---------------------------------------------------------------------------
# Friendly display names
# ---------------------------------------------------------------------------
ENTITY_DISPLAY_NAMES: dict[str, str] = {
    "voltage_l1_l2": "Voltage L1-L2",
    "voltage_l2_l3": "Voltage L2-L3",
    "voltage_l3_l1": "Voltage L3-L1",
    "voltage_l1": "Voltage L1",
    "voltage_l2": "Voltage L2",
    "voltage_l3": "Voltage L3",
    "current_l1": "Current L1",
    "current_l2": "Current L2",
    "current_l3": "Current L3",
    "active_power_total": "Active Power",
    "active_power_l1": "Active Power L1",
    "active_power_l2": "Active Power L2",
    "active_power_l3": "Active Power L3",
    "reactive_power_total": "Reactive Power",
    "reactive_power_l1": "Reactive Power L1",
    "reactive_power_l2": "Reactive Power L2",
    "reactive_power_l3": "Reactive Power L3",
    "apparent_power_total": "Apparent Power",
    "power_factor_total": "Power Factor",
    "power_factor_l1": "Power Factor L1",
    "power_factor_l2": "Power Factor L2",
    "power_factor_l3": "Power Factor L3",
    "frequency": "Frequency",
    "energy_import_total": "Energy Import",
    "energy_export_total": "Energy Export",
    "energy_import_l1": "Energy Import L1",
    "energy_import_l2": "Energy Import L2",
    "energy_import_l3": "Energy Import L3",
}


# ---------------------------------------------------------------------------
# Modbus / TCP client wrapper
# ---------------------------------------------------------------------------

class ModbusTcpHub:
    """Manages a single Modbus/TCP connection (one Elwin adapter)."""

    def __init__(self, host: str, port: int, name: str) -> None:
        self.host = host
        self.port = port
        self.name = name
        self._client: AsyncModbusTcpClient | None = None
        self._lock = asyncio.Lock()

    async def async_connect(self) -> bool:
        """Open a TCP connection to the Modbus gateway."""
        try:
            if self._client is not None:
                self._client.close()
            self._client = AsyncModbusTcpClient(
                host=self.host,
                port=self.port,
                timeout=10,
            )
            connected = await self._client.connect()
            if connected:
                _LOGGER.debug(
                    "Connected to Modbus gateway %s:%s", self.host, self.port
                )
            else:
                _LOGGER.error(
                    "Could not connect to Modbus gateway %s:%s", self.host, self.port
                )
            return connected
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.error(
                "Exception connecting to %s:%s: %s", self.host, self.port, exc
            )
            return False

    async def async_close(self) -> None:
        """Close the TCP connection."""
        if self._client:
            self._client.close()
            self._client = None

    def _is_connected(self) -> bool:
        return self._client is not None and self._client.connected

    async def async_read_meter(
        self,
        slave_id: int,
        model: MeterModel,
    ) -> dict[str, float | None]:
        """
        Read all applicable registers for *model* from slave *slave_id*.
        Returns a dict keyed by register name with float values (or None on error).
        """
        registers = registers_for_model(model)
        result: dict[str, float | None] = {}

        async with self._lock:
            # Ensure we have a live connection before starting the register loop.
            # async_connect is called here, inside the lock, which is safe because
            # this is the only path that mutates self._client.
            if not self._is_connected():
                _LOGGER.debug(
                    "Not connected to %s:%s — reconnecting before reading slave %d",
                    self.host, self.port, slave_id,
                )
                if not await self.async_connect():
                    _LOGGER.error(
                        "Cannot read slave %d on '%s' — gateway unreachable",
                        slave_id, self.name,
                    )
                    return {r.name: None for r in registers}

            _LOGGER.debug(
                "[%s] Starting poll: slave=%d model=%s registers=%d",
                self.name, slave_id, model.value, len(registers),
            )

            for reg in registers:
                try:
                    response = await self._client.read_holding_registers(
                        address=reg.address, count=reg.count, device_id=slave_id
                    )

                    # Guard: None response
                    if response is None:
                        _LOGGER.warning(
                            "[%s] slave=%d reg=%s addr=0x%04X: response is None",
                            self.name, slave_id, reg.name, reg.address,
                        )
                        result[reg.name] = None
                        continue

                    # Guard: Modbus-level error (e.g. illegal address, slave not responding)
                    if hasattr(response, "isError") and response.isError():
                        _LOGGER.warning(
                            "[%s] slave=%d reg=%s addr=0x%04X: error response: %s",
                            self.name, slave_id, reg.name, reg.address, response,
                        )
                        result[reg.name] = None
                        continue

                    # Guard: unexpected response shape (missing .registers attribute)
                    if not hasattr(response, "registers") or len(response.registers) < reg.count:
                        _LOGGER.warning(
                            "[%s] slave=%d reg=%s addr=0x%04X: unexpected response "
                            "type=%s registers=%s",
                            self.name, slave_id, reg.name, reg.address,
                            type(response).__name__,
                            getattr(response, "registers", "<none>"),
                        )
                        result[reg.name] = None
                        continue

                    value = round(
                        self._decode_float32(response.registers) * reg.scale, 4
                    )
                    _LOGGER.debug(
                        "[%s] slave=%d reg=%-30s raw=%s → %.4f %s",
                        self.name, slave_id, reg.name,
                        response.registers, value, reg.unit or "",
                    )
                    result[reg.name] = value

                except ModbusException as exc:
                    _LOGGER.warning(
                        "[%s] slave=%d reg=%s addr=0x%04X: ModbusException: %s",
                        self.name, slave_id, reg.name, reg.address, exc,
                    )
                    result[reg.name] = None

                except Exception as exc:  # pylint: disable=broad-except
                    _LOGGER.error(
                        "[%s] slave=%d reg=%s addr=0x%04X: unexpected %s: %s",
                        self.name, slave_id, reg.name, reg.address,
                        type(exc).__name__, exc,
                    )
                    result[reg.name] = None

        ok = sum(1 for v in result.values() if v is not None)
        _LOGGER.debug(
            "[%s] slave=%d poll complete: %d/%d registers OK",
            self.name, slave_id, ok, len(result),
        )
        return result

    @staticmethod
    def _decode_float32(registers: list[int]) -> float:
        """Decode two 16-bit Modbus registers as a big-endian IEEE-754 float32."""
        raw = struct.pack(">HH", registers[0], registers[1])
        return struct.unpack(">f", raw)[0]
