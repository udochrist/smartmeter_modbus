"""DataUpdateCoordinator for Chint smart meters."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .modbus_client import ModbusTcpHub, MeterModel

_LOGGER = logging.getLogger(__name__)


@dataclass
class AdapterPollStats:
    """Statistics for the adapter's overall poll cycle."""
    last_update: datetime | None = None       # last time ALL meters were polled
    poll_ok_count: int = 0                    # cycles where every meter returned data
    poll_fail_count: int = 0                  # cycles where at least one meter failed

    @property
    def total_polls(self) -> int:
        return self.poll_ok_count + self.poll_fail_count

    @property
    def success_rate(self) -> float | None:
        if self.total_polls == 0:
            return None
        return round(self.poll_ok_count / self.total_polls, 4)


@dataclass
class MeterPollStats:
    """Per-meter last-seen timestamp (meters can fail independently)."""
    last_update: datetime | None = None


class SmartMeterCoordinator(DataUpdateCoordinator):
    """
    Polls all meters on a single Modbus/TCP hub.

    ``data`` is a dict:
        { meter_key: { register_name: float | None, ... }, ... }
    where meter_key = "{slave_id}_{model.value}"

    ``adapter_stats``  — AdapterPollStats for the adapter device diagnostics
    ``meter_stats``    — { meter_key: MeterPollStats } for per-meter last-seen
    """

    def __init__(
        self,
        hass: HomeAssistant,
        hub: ModbusTcpHub,
        meters: list[dict],
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        self.hub = hub
        self.meters = meters
        self.adapter_stats = AdapterPollStats()
        self.meter_stats: dict[str, MeterPollStats] = {
            f"{m['slave_id']}_{m['model']}": MeterPollStats()
            for m in meters
        }

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{hub.name}",
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self) -> dict[str, dict[str, float | None]]:
        result: dict[str, dict[str, float | None]] = {}
        any_failed = False

        for meter_cfg in self.meters:
            slave_id: int = meter_cfg["slave_id"]
            model: MeterModel = MeterModel(meter_cfg["model"])
            key = f"{slave_id}_{model.value}"

            if key not in self.meter_stats:
                self.meter_stats[key] = MeterPollStats()

            try:
                readings = await self.hub.async_read_meter(slave_id, model)
                if any(v is not None for v in readings.values()):
                    self.meter_stats[key].last_update = dt_util.now()
                else:
                    any_failed = True
                result[key] = readings
            except Exception as exc:  # pylint: disable=broad-except
                _LOGGER.error("Failed to poll slave %d: %s", slave_id, exc)
                any_failed = True
                result[key] = {}

        # Adapter-level stats: entire cycle succeeded only if all meters returned data
        if not any_failed:
            self.adapter_stats.poll_ok_count += 1
            self.adapter_stats.last_update = dt_util.now()
        else:
            self.adapter_stats.poll_fail_count += 1

        if not result:
            raise UpdateFailed("All meters failed to return data")

        return result
