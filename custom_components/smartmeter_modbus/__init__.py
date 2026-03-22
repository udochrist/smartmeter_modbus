"""SmartMeter Modbus – Home Assistant integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ADAPTER_NAME,
    CONF_HOST,
    CONF_METERS,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .coordinator import SmartMeterCoordinator
from .modbus_client import ModbusTcpHub

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entry data to current format."""
    _LOGGER.debug("Migrating %s from version %s", entry.entry_id, entry.version)

    if entry.version == 1:
        new_data = dict(entry.data)
        changed = False

        # Ensure slave_id is always stored as int (NumberSelector used to return float)
        meters = []
        for meter in new_data.get(CONF_METERS, []):
            meter = dict(meter)
            if not isinstance(meter.get("slave_id"), int):
                meter["slave_id"] = int(meter["slave_id"])
                changed = True
            meters.append(meter)
        new_data[CONF_METERS] = meters

        # Backfill scan_interval for entries created before this field existed
        if CONF_SCAN_INTERVAL not in new_data:
            new_data[CONF_SCAN_INTERVAL] = DEFAULT_SCAN_INTERVAL
            changed = True

        if changed:
            hass.config_entries.async_update_entry(entry, data=new_data)
            _LOGGER.debug("Migrated config entry %s", entry.entry_id)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SmartMeter Modbus from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    hub = ModbusTcpHub(
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        name=entry.data[CONF_ADAPTER_NAME],
    )

    connected = await hub.async_connect()
    if not connected:
        _LOGGER.error(
            "Failed to connect to Modbus gateway %s:%s",
            entry.data[CONF_HOST],
            entry.data[CONF_PORT],
        )
        # Don't abort – the coordinator will keep retrying.

    scan_interval = int(entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
    coordinator = SmartMeterCoordinator(
        hass=hass,
        hub=hub,
        meters=entry.data.get(CONF_METERS, []),
        scan_interval=scan_interval,
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "hub": hub,
        "coordinator": coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry_data = hass.data[DOMAIN].pop(entry.entry_id)
        await entry_data["hub"].async_close()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
