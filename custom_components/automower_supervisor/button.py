"""Explicit retries for winter parking and Supervisor calendar cleanup."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    """Expose winter retries next to WINTER MODE."""
    async_add_entities([
        AutomowerWinterParkingButton(entry.runtime_data),
        AutomowerWinterCalendarCleanupButton(entry.runtime_data),
    ])


class AutomowerWinterParkingButton(ButtonEntity):
    """Request HOME again when the user has restored mower connectivity."""

    _attr_has_entity_name = True
    _attr_name = "Retry winter parking"
    _attr_icon = "mdi:home-import-outline"
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, manager: AutomowerSupervisorManager) -> None:
        self.manager = manager
        self.entity_id = "button.automower_supervisor_retry_winter_parking"
        self._attr_unique_id = "automower_supervisor_retry_winter_parking"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "global")},
            name="Automower Supervisor",
            manufacturer="Robonect / Husqvarna",
        )

    @property
    def available(self) -> bool:
        return self.manager.winter_mode and not self.manager.winter_parking_in_progress

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self.manager.async_register_callback(self.async_write_ha_state)
        )

    async def async_press(self) -> None:
        await self.manager.async_retry_winter_parking()


class AutomowerWinterCalendarCleanupButton(AutomowerWinterParkingButton):
    """Retry deleting marked Supervisor appointments while remaining paused."""

    _attr_name = "Retry winter calendar cleanup"
    _attr_icon = "mdi:calendar-remove"

    def __init__(self, manager: AutomowerSupervisorManager) -> None:
        super().__init__(manager)
        self.entity_id = "button.automower_supervisor_retry_winter_calendar_cleanup"
        self._attr_unique_id = "automower_supervisor_retry_winter_calendar_cleanup"

    @property
    def available(self) -> bool:
        return self.manager.winter_mode and not self.manager.winter_calendar_cleanup_in_progress

    async def async_press(self) -> None:
        await self.manager.async_retry_winter_calendar_cleanup()
