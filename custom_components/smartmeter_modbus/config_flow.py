"""Config flow for SmartMeter Modbus integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.helpers import selector

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_ADAPTER_NAME,
    CONF_HOST,
    CONF_METERS,
    CONF_MODEL,
    CONF_METER_NAME,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_SLAVE_ID,
    CONF_VENDOR,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    MAX_SCAN_INTERVAL,
    DOMAIN,
    VENDOR_CHINT,
    SUPPORTED_VENDORS,
)
from .modbus_client import MeterModel

_LOGGER = logging.getLogger(__name__)


def _adapter_schema(defaults: dict | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema({
        vol.Required(CONF_ADAPTER_NAME, default=d.get(CONF_ADAPTER_NAME, "Elwin Adapter 1")): str,
        vol.Required(CONF_HOST, default=d.get(CONF_HOST, "")): str,
        vol.Required(CONF_PORT, default=d.get(CONF_PORT, DEFAULT_PORT)): vol.Coerce(int),
        vol.Required(CONF_SCAN_INTERVAL, default=d.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL, step=1,
                mode=selector.NumberSelectorMode.BOX, unit_of_measurement="seconds",
            )
        ),
    })


def _meter_schema(defaults: dict | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema({
        vol.Required(CONF_METER_NAME, default=d.get(CONF_METER_NAME, "")): str,
        vol.Required(CONF_SLAVE_ID, default=d.get(CONF_SLAVE_ID, 1)): selector.NumberSelector(
            selector.NumberSelectorConfig(min=1, max=247, step=1, mode=selector.NumberSelectorMode.BOX)
        ),
        vol.Required(CONF_VENDOR, default=d.get(CONF_VENDOR, VENDOR_CHINT)): selector.SelectSelector(
            selector.SelectSelectorConfig(options=SUPPORTED_VENDORS, mode=selector.SelectSelectorMode.DROPDOWN)
        ),
        vol.Required(CONF_MODEL, default=d.get(CONF_MODEL, MeterModel.DDSU666.value)): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[m.value for m in MeterModel],
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
    })


class SmartMeterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SmartMeter Modbus."""

    VERSION = 1

    def __init__(self) -> None:
        self._adapter_data: dict[str, Any] = {}
        self._meters: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """First step: configure the Modbus/TCP adapter."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # NumberSelector returns float — normalise to int
            user_input[CONF_PORT] = int(user_input[CONF_PORT])
            user_input[CONF_SCAN_INTERVAL] = int(user_input[CONF_SCAN_INTERVAL])
            self._adapter_data = user_input
            unique_id = f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            return await self.async_step_meter_menu()

        return self.async_show_form(
            step_id="user",
            data_schema=_adapter_schema(),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Allow changing all adapter settings (name, host, port, scan interval)."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            new_host = user_input[CONF_HOST]
            new_port = int(user_input[CONF_PORT])
            new_unique_id = f"{new_host}:{new_port}"

            # Only check for duplicate unique_id when host:port actually changed
            if new_unique_id != entry.unique_id:
                await self.async_set_unique_id(new_unique_id)
                self._abort_if_unique_id_configured()

            new_data = {
                **entry.data,
                CONF_ADAPTER_NAME: user_input[CONF_ADAPTER_NAME],
                CONF_HOST: new_host,
                CONF_PORT: new_port,
                CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
            }
            return self.async_update_reload_and_abort(
                entry,
                unique_id=new_unique_id,
                data=new_data,
                reason="reconfigure_successful",
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_adapter_schema(
                defaults={
                    CONF_ADAPTER_NAME: entry.data.get(CONF_ADAPTER_NAME, ""),
                    CONF_HOST: entry.data.get(CONF_HOST, ""),
                    CONF_PORT: entry.data.get(CONF_PORT, DEFAULT_PORT),
                    CONF_SCAN_INTERVAL: entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                }
            ),
            errors=errors,
        )

    async def async_step_meter_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return self.async_show_menu(
            step_id="meter_menu",
            menu_options=["add_meter", "finish"],
            description_placeholders={"meter_count": str(len(self._meters))},
        )

    async def async_step_add_meter(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            # NumberSelector returns float; normalise to int before storing or comparing
            user_input[CONF_SLAVE_ID] = int(user_input[CONF_SLAVE_ID])
            existing_slaves = [m[CONF_SLAVE_ID] for m in self._meters]
            if user_input[CONF_SLAVE_ID] in existing_slaves:
                errors[CONF_SLAVE_ID] = "duplicate_slave_id"
            else:
                self._meters.append(user_input)
                return await self.async_step_meter_menu()

        return self.async_show_form(
            step_id="add_meter",
            data_schema=_meter_schema(),
            errors=errors,
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if not self._meters:
            return await self.async_step_meter_menu()

        data = {**self._adapter_data, CONF_METERS: self._meters}
        return self.async_create_entry(
            title=self._adapter_data[CONF_ADAPTER_NAME],
            data=data,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "SmartMeterOptionsFlow":
        return SmartMeterOptionsFlow(config_entry)


class SmartMeterOptionsFlow(config_entries.OptionsFlow):
    """Options flow: add / remove meters from an existing adapter entry."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._meters: list[dict[str, Any]] = list(
            config_entry.data.get(CONF_METERS, [])
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_meter", "remove_meter", "finish"],
            description_placeholders={"meter_count": str(len(self._meters))},
        )

    async def async_step_add_meter(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            # NumberSelector returns float; normalise to int before storing or comparing
            user_input[CONF_SLAVE_ID] = int(user_input[CONF_SLAVE_ID])
            existing_slaves = [m[CONF_SLAVE_ID] for m in self._meters]
            if user_input[CONF_SLAVE_ID] in existing_slaves:
                errors[CONF_SLAVE_ID] = "duplicate_slave_id"
            else:
                self._meters.append(user_input)
                return await self.async_step_init()

        return self.async_show_form(
            step_id="add_meter",
            data_schema=_meter_schema(),
            errors=errors,
        )

    async def async_step_remove_meter(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            slave_to_remove = int(user_input["slave_id"])
            self._meters = [m for m in self._meters if m[CONF_SLAVE_ID] != slave_to_remove]
            return await self.async_step_init()

        # Keys must be strings — HA form values are always returned as strings
        meter_options = {
            str(m[CONF_SLAVE_ID]): f"{m[CONF_METER_NAME]} (Slave ID {m[CONF_SLAVE_ID]}, {m[CONF_MODEL]})"
            for m in self._meters
        }
        return self.async_show_form(
            step_id="remove_meter",
            data_schema=vol.Schema({
                vol.Required("slave_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=k, label=v)
                            for k, v in meter_options.items()
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }),
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        new_data = {**self._config_entry.data, CONF_METERS: self._meters}
        self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)
        return self.async_create_entry(title="", data={})
