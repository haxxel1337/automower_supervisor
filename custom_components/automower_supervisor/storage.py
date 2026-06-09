"""Storage handling for the Automower Supervisor integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)


class AutomowerSupervisorStorage:
    """Manages persistent storage using Home Assistant Store."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the storage."""
        self.hass = hass
        self._store = Store[dict[str, Any]](hass, STORAGE_VERSION, STORAGE_KEY)

    async def async_load(self) -> dict[str, Any] | None:
        """Load the data from storage."""
        try:
            data = await self._store.async_load()
            return data
        except Exception as err:
            _LOGGER.error("Failed to load Automower Supervisor persistent storage: %s", err)
            return None

    async def async_save(self, data: dict[str, Any]) -> None:
        """Save data to storage immediately."""
        try:
            await self._store.async_save(data)
        except Exception as err:
            _LOGGER.error("Failed to save Automower Supervisor persistent storage: %s", err)

    def async_delay_save(
        self,
        data_callback: Callable[[], dict[str, Any]],
        delay: float = 10.0,
    ) -> None:
        """Delay saving to storage and resolve the latest data at write time."""
        try:
            self._store.async_delay_save(data_callback, delay)
        except Exception as err:
            _LOGGER.error(
                "Failed to schedule delayed save for Automower Supervisor: %s",
                err,
            )
