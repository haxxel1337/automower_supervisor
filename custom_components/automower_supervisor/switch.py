"""Persistent winter controls on the central Automower Supervisor device."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .manager import AutomowerSupervisorManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[AutomowerSupervisorManager],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the winter mode switch to the existing global device."""
    async_add_entities([AutomowerWinterModeSwitch(entry.runtime_data)])


class AutomowerWinterModeSwitch(SwitchEntity):
    """Pause Supervisor and request HOME until explicitly turned off."""

    _attr_has_entity_name = True
    _attr_name = "WINTER MODE"
    _attr_icon = "mdi:snowflake"
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, manager: AutomowerSupervisorManager) -> None:
        self.manager = manager
        self.entity_id = "switch.automower_supervisor_winter_mode"
        self._attr_unique_id = "automower_supervisor_winter_mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "global")},
            name="Automower Supervisor",
            manufacturer="Robonect / Husqvarna",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self.manager.async_register_callback(self.async_write_ha_state)
        )

    @property
    def is_on(self) -> bool:
        return self.manager.winter_mode

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "changed_at": self.manager.winter_mode_changed_at,
            "parking_in_progress": self.manager.winter_parking_in_progress,
            "parking_results": {
                robot_id: dict(result)
                for robot_id, result in self.manager.winter_parking_results.items()
            },
            "storage_error": self.manager.winter_storage_error,
            "parking_note": "HOME requests do not confirm physical arrival at the dock.",
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.manager.async_set_winter_mode(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.manager.async_set_winter_mode(False)
