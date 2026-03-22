"""Sensor platform for SmartMeter Modbus integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfApparentPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfReactivePower,
)
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ADAPTER_NAME,
    CONF_HOST,
    CONF_METERS,
    CONF_METER_NAME,
    CONF_MODEL,
    CONF_PORT,
    CONF_SLAVE_ID,
    CONF_VENDOR,
    DIAG_LAST_UPDATE,
    DIAG_POLL_FAIL_COUNT,
    DIAG_POLL_OK_COUNT,
    DIAG_POLL_SUCCESS_RATE,
    DOMAIN,
)
from .coordinator import MeterPollStats
from .coordinator import AdapterPollStats, SmartMeterCoordinator, MeterPollStats
from .modbus_client import (
    ENTITY_DISPLAY_NAMES,
    MeterModel,
    RegisterDefinition,
    registers_for_model,
)

_LOGGER = logging.getLogger(__name__)

# Map unit strings to HA unit constants
_UNIT_MAP: dict[str | None, str | None] = {
    "V": UnitOfElectricPotential.VOLT,
    "A": UnitOfElectricCurrent.AMPERE,
    "W": UnitOfPower.WATT,
    "var": UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
    "VA": UnitOfApparentPower.VOLT_AMPERE,
    "kWh": UnitOfEnergy.KILO_WATT_HOUR,
    "Hz": UnitOfFrequency.HERTZ,
    None: None,
}

_DEVICE_CLASS_MAP: dict[str | None, SensorDeviceClass | None] = {
    "voltage": SensorDeviceClass.VOLTAGE,
    "current": SensorDeviceClass.CURRENT,
    "power": SensorDeviceClass.POWER,
    "reactive_power": SensorDeviceClass.REACTIVE_POWER,
    "apparent_power": SensorDeviceClass.APPARENT_POWER,
    "energy": SensorDeviceClass.ENERGY,
    "frequency": SensorDeviceClass.FREQUENCY,
    "power_factor": SensorDeviceClass.POWER_FACTOR,
    None: None,
}

_STATE_CLASS_MAP: dict[str | None, SensorStateClass | None] = {
    "measurement": SensorStateClass.MEASUREMENT,
    "total_increasing": SensorStateClass.TOTAL_INCREASING,
    None: None,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities for every meter on this adapter."""
    from homeassistant.helpers import device_registry as dr

    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: SmartMeterCoordinator = entry_data["coordinator"]
    adapter_name: str = entry.data[CONF_ADAPTER_NAME]
    adapter_host: str = entry.data[CONF_HOST]
    adapter_port: int = entry.data[CONF_PORT]

    # Register the adapter itself as a real device so meters can reference it
    # via via_device without triggering the "non-existing via_device" warning.
    adapter_device_identifier = f"{entry.entry_id}_adapter"
    dev_reg = dr.async_get(hass)
    dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, adapter_device_identifier)},
        name=adapter_name,
        manufacturer="Elwin",
        model="Modbus/TCP Converter",
        configuration_url=f"http://{adapter_host}:{adapter_port}",
    )

    from homeassistant.helpers import entity_registry as er

    entities: list[SmartMeterSensor] = []
    valid_unique_ids: set[str] = set()

    for meter_cfg in entry.data.get(CONF_METERS, []):
        slave_id: int = meter_cfg[CONF_SLAVE_ID]
        model = MeterModel(meter_cfg[CONF_MODEL])
        meter_name: str = meter_cfg[CONF_METER_NAME]
        vendor: str = meter_cfg[CONF_VENDOR]
        meter_key = f"{slave_id}_{model.value}"

        device_unique_id = f"{entry.entry_id}_{meter_key}"

        device_info = DeviceInfo(
            identifiers={(DOMAIN, device_unique_id)},
            name=meter_name,
            manufacturer=vendor,
            model=model.value,
            via_device=(DOMAIN, adapter_device_identifier),
            configuration_url=f"http://{adapter_host}",
        )

        for reg in registers_for_model(model):
            uid = f"{device_unique_id}_{reg.name}"
            valid_unique_ids.add(uid)
            entities.append(
                SmartMeterSensor(
                    coordinator=coordinator,
                    meter_key=meter_key,
                    reg=reg,
                    device_info=device_info,
                    device_unique_id=device_unique_id,
                    meter_name=meter_name,
                )
            )

    # Remove stale entities that no longer correspond to any register
    # (e.g. apparent_power_total left over from a previous version on DDSU-666)
    ent_reg = er.async_get(hass)
    for entity_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if entity_entry.unique_id not in valid_unique_ids:
            _LOGGER.debug(
                "Removing stale entity %s (unique_id=%s)",
                entity_entry.entity_id, entity_entry.unique_id,
            )
            ent_reg.async_remove(entity_entry.entity_id)

    # Adapter-level diagnostic entities (on the Elwin adapter device)
    adapter_device_info = DeviceInfo(identifiers={(DOMAIN, adapter_device_identifier)})
    entities += [
        AdapterLastUpdateSensor(coordinator, entry.entry_id, adapter_device_info),
        AdapterPollCountSensor(
            coordinator, entry.entry_id, adapter_device_info,
            key=DIAG_POLL_OK_COUNT, name="Successful Poll Cycles",
            icon="mdi:check-circle-outline",
        ),
        AdapterPollCountSensor(
            coordinator, entry.entry_id, adapter_device_info,
            key=DIAG_POLL_FAIL_COUNT, name="Failed Poll Cycles",
            icon="mdi:alert-circle-outline",
        ),
        AdapterSuccessRateSensor(coordinator, entry.entry_id, adapter_device_info),
    ]

    # Per-meter: only Last Update (each meter can fail independently)
    for meter_cfg in entry.data.get(CONF_METERS, []):
        slave_id_d: int = meter_cfg[CONF_SLAVE_ID]
        model_d = MeterModel(meter_cfg[CONF_MODEL])
        meter_name_d: str = meter_cfg[CONF_METER_NAME]
        vendor_d: str = meter_cfg[CONF_VENDOR]
        meter_key_d = f"{slave_id_d}_{model_d.value}"
        device_unique_id_d = f"{entry.entry_id}_{meter_key_d}"
        meter_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_unique_id_d)},
            name=meter_name_d,
            manufacturer=vendor_d,
            model=model_d.value,
            via_device=(DOMAIN, adapter_device_identifier),
            configuration_url=f"http://{adapter_host}",
        )
        entities.append(
            MeterLastUpdateSensor(coordinator, meter_key_d, device_unique_id_d, meter_device_info)
        )

    async_add_entities(entities)


class SmartMeterSensor(CoordinatorEntity[SmartMeterCoordinator], SensorEntity):
    """Represents one data-point of a Chint smart meter."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SmartMeterCoordinator,
        meter_key: str,
        reg: RegisterDefinition,
        device_info: DeviceInfo,
        device_unique_id: str,
        meter_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._meter_key = meter_key
        self._reg = reg

        self._attr_unique_id = f"{device_unique_id}_{reg.name}"
        self._attr_name = ENTITY_DISPLAY_NAMES.get(reg.name, reg.name.replace("_", " ").title())
        self._attr_native_unit_of_measurement = _UNIT_MAP.get(reg.unit, reg.unit)
        self._attr_device_class = _DEVICE_CLASS_MAP.get(reg.device_class)
        self._attr_state_class = _STATE_CLASS_MAP.get(reg.state_class)
        self._attr_device_info = device_info
        self._attr_suggested_display_precision = 2

    @property
    def native_value(self) -> float | None:
        """Return the current sensor value."""
        if self.coordinator.data is None:
            return None
        meter_data = self.coordinator.data.get(self._meter_key, {})
        return meter_data.get(self._reg.name)

    @property
    def available(self) -> bool:
        """Sensor is available when coordinator has data and value is not None."""
        if not super().available or self.coordinator.data is None:
            return False
        meter_data = self.coordinator.data.get(self._meter_key, {})
        return meter_data.get(self._reg.name) is not None


# ---------------------------------------------------------------------------
# Diagnostic sensor entities
# ---------------------------------------------------------------------------
# Adapter-level: poll cycle stats live on the Elwin gateway device.
# Meter-level:   only Last Update per meter (meters can fail independently).
# ---------------------------------------------------------------------------

class AdapterLastUpdateSensor(CoordinatorEntity[SmartMeterCoordinator], SensorEntity):
    """Timestamp of the last fully successful poll cycle on this adapter."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-check-outline"

    def __init__(self, coordinator, entry_id, device_info):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_adapter_{DIAG_LAST_UPDATE}"
        self._attr_name = "Last Poll"
        self._attr_device_info = device_info

    @property
    def native_value(self):
        return self.coordinator.adapter_stats.last_update

    @property
    def available(self) -> bool:
        return True


class AdapterPollCountSensor(CoordinatorEntity[SmartMeterCoordinator], SensorEntity):
    """Cumulative count of successful or failed poll cycles on this adapter."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "cycles"

    def __init__(self, coordinator, entry_id, device_info, key, name, icon):
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{entry_id}_adapter_{key}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_device_info = device_info

    @property
    def native_value(self) -> int:
        s = self.coordinator.adapter_stats
        return s.poll_ok_count if self._key == DIAG_POLL_OK_COUNT else s.poll_fail_count

    @property
    def available(self) -> bool:
        return True


class AdapterSuccessRateSensor(CoordinatorEntity[SmartMeterCoordinator], SensorEntity):
    """Poll cycle success rate for this adapter (0–100 %)."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:chart-line"
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator, entry_id, device_info):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_adapter_{DIAG_POLL_SUCCESS_RATE}"
        self._attr_name = "Poll Success Rate"
        self._attr_device_info = device_info

    @property
    def native_value(self) -> float | None:
        rate = self.coordinator.adapter_stats.success_rate
        return round(rate * 100, 1) if rate is not None else None

    @property
    def available(self) -> bool:
        return True


class MeterLastUpdateSensor(CoordinatorEntity[SmartMeterCoordinator], SensorEntity):
    """Timestamp of the last successful data read for this specific meter."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-check-outline"

    def __init__(self, coordinator, meter_key, device_unique_id, device_info):
        super().__init__(coordinator)
        self._meter_key = meter_key
        self._attr_unique_id = f"{device_unique_id}_{DIAG_LAST_UPDATE}"
        self._attr_name = "Last Update"
        self._attr_device_info = device_info

    @property
    def native_value(self):
        stats = self.coordinator.meter_stats.get(self._meter_key)
        return stats.last_update if stats else None

    @property
    def available(self) -> bool:
        return True
