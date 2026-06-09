"""The Automower Supervisor custom integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .manager import AutomowerSupervisorManager

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]

# Type annotation helper for config entries
# In Python <3.12 we can just annotate directly as ConfigEntry[AutomowerSupervisorManager]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry[AutomowerSupervisorManager]) -> bool:
    """Set up Automower Supervisor from a config entry."""
    _LOGGER.info("Setting up Automower Supervisor entry: %s", entry.entry_id)

    # Initialize the central manager
    manager = AutomowerSupervisorManager(hass)
    await manager.async_setup()

    # Store manager in runtime_data
    entry.runtime_data = manager

    # Forward setup to the sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry[AutomowerSupervisorManager]) -> bool:
    """Unload Automower Supervisor config entry."""
    _LOGGER.info("Unloading Automower Supervisor entry: %s", entry.entry_id)

    # Clean up listeners and persist current state
    manager = entry.runtime_data
    await manager.async_unload()

    # Unload sensor platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    return unload_ok
