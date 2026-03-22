"""Diagnostics for SmartMeter Modbus.

Accessible via: Settings → Devices & Services → [your adapter] → ⋮ → Download diagnostics
The downloaded JSON shows every register address, its raw 16-bit words, decoded float,
scaled engineering value, and unit — useful for debugging wrong/unavailable values.
"""
from __future__ import annotations

import struct
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_HOST, CONF_METERS, CONF_PORT, DOMAIN
from .coordinator import SmartMeterCoordinator
from .modbus_client import MeterModel, registers_for_model

_LOGGER = logging.getLogger(__name__)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry (one Modbus/TCP adapter)."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: SmartMeterCoordinator = entry_data["coordinator"]
    hub = entry_data["hub"]

    coordinator_data = coordinator.data or {}

    # Do a fresh raw read for each meter so we can capture the raw register words
    raw_reads: dict[str, dict[str, Any]] = {}
    for meter_cfg in entry.data.get(CONF_METERS, []):
        slave_id: int = meter_cfg["slave_id"]
        model = MeterModel(meter_cfg["model"])
        meter_key = f"{slave_id}_{model.value}"

        register_raws: list[dict[str, Any]] = []
        try:
            async with hub._lock:
                if not hub._is_connected():
                    await hub.async_connect()

                for reg in registers_for_model(model):
                    entry_info: dict[str, Any] = {
                        "name": reg.name,
                        "address_hex": f"0x{reg.address:04X}",
                        "unit": reg.unit,
                        "scale": reg.scale,
                    }
                    try:
                        response = await hub._client.read_holding_registers(
                            address=reg.address, count=reg.count, device_id=slave_id
                        )
                        if response is None or (hasattr(response, "isError") and response.isError()):
                            entry_info["raw_registers"] = None
                            entry_info["raw_hex"] = None
                            entry_info["decoded_float"] = None
                            entry_info["scaled_value"] = None
                            entry_info["error"] = str(response)
                        else:
                            regs = response.registers
                            raw_bytes = struct.pack(">HH", regs[0], regs[1])
                            decoded = struct.unpack(">f", raw_bytes)[0]
                            entry_info["raw_registers"] = regs
                            entry_info["raw_hex"] = [f"0x{r:04X}" for r in regs]
                            entry_info["decoded_float"] = round(decoded, 6)
                            entry_info["scaled_value"] = round(decoded * reg.scale, 4)
                    except Exception as exc:  # pylint: disable=broad-except
                        entry_info["raw_registers"] = None
                        entry_info["error"] = f"{type(exc).__name__}: {exc}"

                    register_raws.append(entry_info)
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.warning("Diagnostics read failed for slave %d: %s", slave_id, exc)

        raw_reads[meter_key] = {
            "name": meter_cfg.get("meter_name", meter_key),
            "slave_id": slave_id,
            "model": model.value,
            "registers": register_raws,
        }

    return {
        "adapter": {
            "name": entry.data.get("adapter_name"),
            "host": entry.data.get(CONF_HOST),
            "port": entry.data.get(CONF_PORT),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "last_poll_values": coordinator_data,
        },
        "live_register_dump": raw_reads,
    }
