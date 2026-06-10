"""Config flow for the Automower Supervisor integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_CALENDAR_ENTITY_ID,
    CONF_CALENDAR_ENABLED,
    CONF_EVENING_SYNC_TIME,
    CONF_MORNING_SYNC_TIME,
    CONF_CALENDAR_EVENT_START_TIME,
    CONF_CALENDAR_EVENT_DURATION,
    DEFAULT_EVENING_SYNC_TIME,
    DEFAULT_MORNING_SYNC_TIME,
    DEFAULT_CALENDAR_EVENT_START_TIME,
    DEFAULT_CALENDAR_EVENT_DURATION,
)

_LOGGER = logging.getLogger(__name__)


class AutomowerSupervisorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Automower Supervisor."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step where the user triggers configuration."""
        _LOGGER.debug("Config flow user step triggered")

        # Prevent multiple installations
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        if user_input is not None:
            # Sätt ett stabilt unikt id baserat på domänen
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title="Automower Supervisor",
                data={},
            )

        return self.async_show_form(
            step_id="user",
            data_schema=None,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return AutomowerSupervisorOptionsFlowHandler()


class AutomowerSupervisorOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Automower Supervisor."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options

        schema = vol.Schema({
            vol.Optional(
                CONF_CALENDAR_ENABLED,
                default=options.get(CONF_CALENDAR_ENABLED, False)
            ): bool,
            vol.Optional(
                CONF_CALENDAR_ENTITY_ID,
                default=options.get(CONF_CALENDAR_ENTITY_ID, "")
            ): selector.selector({"entity": {"domain": "calendar"}}),
            vol.Optional(
                CONF_EVENING_SYNC_TIME,
                default=options.get(CONF_EVENING_SYNC_TIME, DEFAULT_EVENING_SYNC_TIME)
            ): str,
            vol.Optional(
                CONF_MORNING_SYNC_TIME,
                default=options.get(CONF_MORNING_SYNC_TIME, DEFAULT_MORNING_SYNC_TIME)
            ): str,
            vol.Optional(
                CONF_CALENDAR_EVENT_START_TIME,
                default=options.get(CONF_CALENDAR_EVENT_START_TIME, DEFAULT_CALENDAR_EVENT_START_TIME)
            ): str,
            vol.Optional(
                CONF_CALENDAR_EVENT_DURATION,
                default=options.get(CONF_CALENDAR_EVENT_DURATION, DEFAULT_CALENDAR_EVENT_DURATION)
            ): int,
        })

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
        )

