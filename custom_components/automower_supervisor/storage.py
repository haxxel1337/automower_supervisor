"""Storage handling for the Automower Supervisor integration."""

from __future__ import annotations

import logging
import asyncio
from copy import deepcopy
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
        self._save_lock = asyncio.Lock()
        self._winter_override = None
        self._load_failed = False

    async def async_load(self) -> dict[str, Any] | None:
        """Load the data from storage."""
        try:
            data = await self._store.async_load()
            return data
        except Exception as err:
            _LOGGER.error("Failed to load Automower Supervisor persistent storage: %s", err)
            return None

    async def async_load_strict(self) -> dict[str, Any] | None:
        """Load safety-relevant configuration without hiding storage failures."""
        try:
            data = await self._store.async_load()
            if data is not None and not isinstance(data, dict):
                raise ValueError("Supervisor storage must contain an object")
        except Exception:
            self._load_failed = True
            raise
        self._load_failed = False
        return data

    async def async_save_strict(self, data: dict[str, Any]) -> None:
        """Persist a winter-mode transition, propagating failures to the caller."""
        if self._load_failed:
            raise RuntimeError("Storage could not be read; reload Supervisor before changing winter mode")
        async with self._save_lock:
            await self._store.async_save(data)
            if "_winter" in data:
                self._winter_override = deepcopy(data["_winter"])

    async def async_save(self, data: dict[str, Any]) -> None:
        """Save data to storage immediately."""
        if self._load_failed:
            _LOGGER.error("Preserving unread Supervisor storage; write skipped")
            return
        try:
            async with self._save_lock:
                if self._winter_override is not None:
                    winter = data.get("_winter", {})
                    if any(winter.get(key) != self._winter_override.get(key)
                           for key in ("enabled", "changed_at", "resume_date")):
                        data = {**data, "_winter": deepcopy(self._winter_override)}
                await self._store.async_save(data)
        except Exception as err:
            _LOGGER.error("Failed to save Automower Supervisor persistent storage: %s", err)

    def async_delay_save(
        self,
        data_callback: Callable[[], dict[str, Any]],
        delay: float = 10.0,
    ) -> None:
        """Delay saving to storage and resolve the latest data at write time."""
        if self._load_failed:
            return
        try:
            self._store.async_delay_save(data_callback, delay)
        except Exception as err:
            _LOGGER.error(
                "Failed to schedule delayed save for Automower Supervisor: %s",
                err,
            )
