"""Config flow for the Automower Supervisor integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN

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
