"""Sensor platform for the Automower Supervisor integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, NO_ACTIVE_ERROR_VALUES
from .manager import AutomowerSupervisorManager, get_robot_suffix
from .models import RecoveryState

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[AutomowerSupervisorManager],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Automower Supervisor sensors."""
    manager = entry.runtime_data
    _LOGGER.debug("Setting up Automower Supervisor sensor platform")

    entities: list[SensorEntity] = []

    # Add individual robot sensors
    for robot_id in manager.robots:
        entities.append(AutomowerRobotSensor(robot_id, manager))

    # Add the central discovery sensor
    entities.append(AutomowerDiscoverySensor(manager))

    async_add_entities(entities)


class AutomowerRobotSensor(SensorEntity):
    """Monitors the state and errors of an individual robotic lawn mower."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:robot-mower"
    _attr_should_poll = False

    def __init__(self, robot_id: str, manager: AutomowerSupervisorManager) -> None:
        """Initialize the robot sensor."""
        self.robot_id = robot_id
        self.manager = manager
        
        suffix = get_robot_suffix(robot_id)
        self.entity_id = f"sensor.automower_supervisor_{suffix}"
        self._attr_unique_id = f"automower_supervisor_{robot_id}"
        
        state_data = self.manager.robots[self.robot_id]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.robot_id)},
            name=f"Automower Supervisor {state_data.display_name}",
            manufacturer="Robonect / Husqvarna",
        )

    async def async_added_to_hass(self) -> None:
        """Register callbacks when entity is added to Home Assistant."""
        _LOGGER.debug("Adding robot sensor to hass: %s", self.entity_id)
        self.async_on_remove(
            self.manager.async_register_callback(self.async_write_ha_state)
        )

    @property
    def native_value(self) -> str:
        """Return the state of the sensor."""
        state_data = self.manager.robots[self.robot_id]

        # 1. Critical state (active error or cleared but unverified)
        is_critical = (
            state_data.current_error_active
            or state_data.recovery_state in (RecoveryState.ACTIVE_ERROR, RecoveryState.CLEARED_BUT_UNVERIFIED)
        )
        if is_critical:
            return "critical"

        # 2. Critical state due to offline (online = False)
        if state_data.online is False:
            return "critical"

        # 3. Warning state due to stale data
        if state_data.online is True and state_data.source_age_minutes is not None and 15 < state_data.source_age_minutes <= 60:
            return "warning"

        # 4. Warning / Insufficient Data state based on HA entity status
        central_keys = ["status", "status_plain", "battery", "error_message", "error_binary", "clock"]
        
        missing_centrals = [
            state_data.entity_ids[k] for k in central_keys
            if state_data.entity_ids[k] in state_data.missing_entities
        ]
        unavailable_centrals = [
            state_data.entity_ids[k] for k in central_keys
            if state_data.entity_ids[k] in state_data.unavailable_entities
        ]
        unknown_centrals = [
            state_data.entity_ids[k] for k in central_keys
            if state_data.entity_ids[k] in state_data.unknown_entities
        ]

        # Insufficient data if fewer than 2 central entities are available (with useful values)
        available_count = len(central_keys) - len(missing_centrals) - len(unavailable_centrals) - len(unknown_centrals)
        if available_count < 2:
            return "insufficient_data"

        # Warning state if any central entity is missing, unavailable or unknown
        if missing_centrals or unavailable_centrals or unknown_centrals:
            return "warning"

        return "ok"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details about the assessment reasons and sub-entity states."""
        state_data = self.manager.robots[self.robot_id]

        # Determine assessment reasons
        reasons: list[str] = []
        
        is_real_error = False
        if state_data.current_error_message:
            norm = state_data.current_error_message.strip().lower()
            if norm and norm not in NO_ACTIVE_ERROR_VALUES:
                is_real_error = True

        if is_real_error:
            reasons.append("ACTIVE_ERROR_MESSAGE")
        if state_data.binary_error == "on":
            reasons.append("BINARY_ERROR_ON")
        if state_data.recovery_state == RecoveryState.CLEARED_BUT_UNVERIFIED:
            reasons.append("CLEARED_BUT_UNVERIFIED")

        # Watchdog status reason codes
        if state_data.online is False:
            reasons.append("ROBOT_OFFLINE")
        elif state_data.online is True and state_data.source_age_minutes is not None and 15 < state_data.source_age_minutes <= 60:
            reasons.append("STALE_SOURCE_DATA")
        elif state_data.online is None:
            reasons.append("NO_HEARTBEAT_DATA")

        central_keys = ["status", "status_plain", "battery", "error_message", "error_binary", "clock"]
        missing_centrals = [
            state_data.entity_ids[k] for k in central_keys
            if state_data.entity_ids[k] in state_data.missing_entities
        ]
        unavailable_centrals = [
            state_data.entity_ids[k] for k in central_keys
            if state_data.entity_ids[k] in state_data.unavailable_entities
        ]
        unknown_centrals = [
            state_data.entity_ids[k] for k in central_keys
            if state_data.entity_ids[k] in state_data.unknown_entities
        ]

        if missing_centrals:
            reasons.append("MISSING_ENTITIES")
        if unavailable_centrals:
            reasons.append("UNAVAILABLE_ENTITIES")
        if unknown_centrals:
            reasons.append("UNKNOWN_ENTITIES")

        available_count = len(central_keys) - len(missing_centrals) - len(unavailable_centrals) - len(unknown_centrals)
        if available_count < 2:
            reasons.append("INSUFFICIENT_DATA")

        source_values_stale = (
            state_data.online is False
            or state_data.online is None
            or (state_data.source_age_minutes is not None and state_data.source_age_minutes > 15)
        )

        return {
            "robot_id": self.robot_id,
            "display_name": state_data.display_name,
            "current_status": state_data.current_status,
            "current_status_plain": state_data.current_status_plain,
            "current_battery": state_data.current_battery,
            "current_error_message": state_data.current_error_message,
            "binary_error": state_data.binary_error,
            "last_real_error": state_data.last_real_error,
            "last_real_error_at": state_data.last_real_error_at,
            "error_cleared_at": state_data.error_cleared_at,
            "current_error_active": state_data.current_error_active,
            "recovery_state": str(state_data.recovery_state.value),
            "missing_entities": state_data.missing_entities,
            "unavailable_entities": state_data.unavailable_entities,
            "unknown_entities": state_data.unknown_entities,
            "last_event_at": state_data.last_event_at,
            "entity_ids": state_data.entity_ids,
            "assessment_reasons": reasons,
            "online": state_data.online,
            "last_source_update_at": state_data.last_source_update_at,
            "source_age_minutes": state_data.source_age_minutes,
            "stale_entities": state_data.stale_entities,
            "watchdog_checked_at": self.manager.watchdog_checked_at,
            "source_values_stale": source_values_stale,
        }


class AutomowerDiscoverySensor(SensorEntity):
    """Exposes summary information about the discovered entity landscape."""

    _attr_has_entity_name = True
    _attr_name = "Discovery"
    _attr_icon = "mdi:magnify-scan"
    _attr_should_poll = False

    def __init__(self, manager: AutomowerSupervisorManager) -> None:
        """Initialize the discovery sensor."""
        self.manager = manager
        self.entity_id = "sensor.automower_supervisor_discovery"
        self._attr_unique_id = "automower_supervisor_discovery"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "global")},
            name="Automower Supervisor",
            manufacturer="Robonect / Husqvarna",
        )

    async def async_added_to_hass(self) -> None:
        """Register callbacks when entity is added to Home Assistant."""
        _LOGGER.debug("Adding discovery sensor to hass")
        self.async_on_remove(
            self.manager.async_register_callback(self.async_write_ha_state)
        )

    @property
    def native_value(self) -> int:
        """Return the number of mowers with at least one discovered entity."""
        count = 0
        for state_data in self.manager.robots.values():
            if len(state_data.missing_entities) < len(state_data.entity_ids):
                count += 1
        return count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return diagnostic metrics about expected vs missing vs unavailable vs unknown entities."""
        robots_dict = {}
        total_expected = 0
        total_missing = 0
        total_unavailable = 0
        total_unknown = 0
        robots_online = 0
        robots_stale = 0
        robots_offline = 0
        robots_unknown_online_state = 0

        for robot_id, state_data in self.manager.robots.items():
            # Watchdog status counts
            if state_data.online is True:
                if state_data.source_age_minutes is not None and state_data.source_age_minutes <= 15:
                    robots_online += 1
                else:
                    robots_stale += 1
            elif state_data.online is False:
                robots_offline += 1
            else:
                robots_unknown_online_state += 1

            found_keys = []
            missing_keys = []
            unavailable_keys = []
            unknown_keys = []

            for key, entity_id in state_data.entity_ids.items():
                total_expected += 1
                if entity_id in state_data.missing_entities:
                    missing_keys.append(key)
                    total_missing += 1
                elif entity_id in state_data.unavailable_entities:
                    unavailable_keys.append(key)
                    total_unavailable += 1
                elif entity_id in state_data.unknown_entities:
                    unknown_keys.append(key)
                    total_unknown += 1
                else:
                    found_keys.append(key)

            robots_dict[robot_id] = {
                "display_name": state_data.display_name,
                "found": found_keys,
                "missing": missing_keys,
                "unavailable": unavailable_keys,
                "unknown": unknown_keys,
                "online": state_data.online,
                "source_age_minutes": state_data.source_age_minutes,
                "last_source_update_at": state_data.last_source_update_at,
            }

        total_found = total_expected - total_missing - total_unavailable - total_unknown

        return {
            "robots_configured": len(self.manager.robots),
            "robots_found": self.native_value,
            "entities_expected": total_expected,
            "entities_found": total_found,
            "entities_missing": total_missing,
            "entities_unavailable": total_unavailable,
            "entities_unknown": total_unknown,
            "robots_online": robots_online,
            "robots_stale": robots_stale,
            "robots_offline": robots_offline,
            "robots_unknown_online_state": robots_unknown_online_state,
            "watchdog_checked_at": self.manager.watchdog_checked_at,
            "robots": robots_dict,
        }
