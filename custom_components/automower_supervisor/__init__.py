"""The Automower Supervisor custom integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from . import compat_0512
from .manager import AutomowerSupervisorManager

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]

# Type annotation helper for config entries
# In Python <3.12 we can just annotate directly as ConfigEntry[AutomowerSupervisorManager]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry[AutomowerSupervisorManager]) -> bool:
    """Set up Automower Supervisor from a config entry."""
    _LOGGER.info("Setting up Automower Supervisor entry: %s", entry.entry_id)

    # Install compatibility/behavior patches before the manager builds entity IDs.
    compat_0512.install()

    # Initialize the central manager
    manager = AutomowerSupervisorManager(hass)
    await manager.async_setup()

    # Store manager in runtime_data
    entry.runtime_data = manager

    # Forward setup to the sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register options update listener to reload on options change
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options are changed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry[AutomowerSupervisorManager]) -> bool:
    """Unload Automower Supervisor config entry."""
    _LOGGER.info("Unloading Automower Supervisor entry: %s", entry.entry_id)

    # Unload sensor platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Clean up listeners and persist current state
        manager = entry.runtime_data
        await manager.async_unload()

    return unload_ok
