"""Sensor platform for the Automower Supervisor integration."""

from __future__ import annotations

import logging
from typing import Any
from datetime import datetime

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import homeassistant.util.dt as dt_util

from .const import DOMAIN, NO_ACTIVE_ERROR_VALUES
from .manager import AutomowerSupervisorManager, get_robot_suffix
from .models import RecoveryState, RobotState
from .schedule import is_scheduled_now
from .daily_assessment import is_attempt_from_today

_LOGGER = logging.getLogger(__name__)


def _append_pending_reason_codes(
    reasons: list[str],
    state_data: RobotState,
) -> None:
    """Append pending reason codes based on active pending mowing confirmation status."""
    if not state_data.pending_mowing_confirmation:
        return

    reasons.append("PENDING_MOWING_CONFIRMATION")

    if state_data.pending_confirmation_type == "full_mowing":
        reasons.append("CONFIRMATION_PENDING")
    elif state_data.pending_confirmation_type == "recovery_only":
        reasons.append("RECOVERY_CONFIRMATION_PENDING")
    else:
        reasons.append("PENDING_CONFIRMATION_TYPE_INVALID")


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

    # Add the central summary sensor
    entities.append(AutomowerSupervisorSummarySensor(manager))

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
        now = dt_util.now()
        attempt_is_today = is_attempt_from_today(state_data, now)

        # 1. Critical state (active error or cleared but unverified or failed recovery or offline)
        is_critical = (
            state_data.current_error_active
            or state_data.binary_error == "on"
            or state_data.recovery_state in (RecoveryState.ACTIVE_ERROR, RecoveryState.CLEARED_BUT_UNVERIFIED)
            or state_data.failed_recovery
            or state_data.online is False
        )
        if is_critical:
            return "critical"

        # 2. Warning when Charging is reported but battery decreases
        if state_data.charging_stalled:
            return "warning"

        # 3. Warning state due to stale data (takes precedence over insufficient data)
        if state_data.online is True and state_data.source_age_minutes is not None and 15 < state_data.source_age_minutes <= 60:
            return "warning"

        # 3. Check for Insufficient Data state based on HA entity status
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

        # 4. Warning state due to uncertain mowing session attempts (only if attempt is from today)
        attempt_warning_results = {
            "short_attempt",
            "uncertain_attempt",
            "interrupted_searching",
            "session_lost_offline",
            "insufficient_supporting_data",
            "failed_error_during_mowing",
            "failed_error_after_mowing",
            "recovery_confirmation_invalid",
        }
        if (
            attempt_is_today
            and state_data.last_mowing_attempt_result in attempt_warning_results
        ):
            return "warning"

        # 5. Warning state if schedule active, attempted but not confirmed today
        if is_scheduled_now(now):
            if state_data.mowing_attempted_today and not state_data.confirmed_mowing_today:
                return "warning"

        # 6. Warning state if mowing is active but not yet confirmed today
        if state_data.mowing_session_active and not state_data.confirmed_mowing_today:
            return "warning"

        # Warning state if any central entity is missing, unavailable or unknown
        if missing_centrals or unavailable_centrals or unknown_centrals:
            return "warning"

        return "ok"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details about the assessment reasons and sub-entity states."""
        state_data = self.manager.robots[self.robot_id]
        now = dt_util.now()
        attempt_is_today = is_attempt_from_today(state_data, now)

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

        if state_data.charging_stalled:
            reasons.append("CHARGING_STALLED")

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

        # Mowing Session / Attempt Reason Codes
        if state_data.mowing_session_active:
            reasons.append("MOWING_SESSION_ACTIVE")
            
        if attempt_is_today:
            if state_data.last_mowing_attempt_result == "short_attempt":
                reasons.append("MOWING_ATTEMPT_SHORT")
            elif state_data.last_mowing_attempt_result == "uncertain_attempt":
                reasons.append("MOWING_ATTEMPT_UNCERTAIN")
            elif state_data.last_mowing_attempt_result == "interrupted_searching":
                reasons.append("MOWING_INTERRUPTED_SEARCHING")
            elif state_data.last_mowing_attempt_result == "confirmed_mowing":
                reasons.append("CONFIRMED_MOWING")
            elif state_data.last_mowing_attempt_result == "failed_error_during_mowing":
                reasons.append("ERROR_DURING_MOWING")
            elif state_data.last_mowing_attempt_result == "failed_error_after_mowing":
                reasons.append("ERROR_AFTER_MOWING")
            elif state_data.last_mowing_attempt_result == "insufficient_supporting_data":
                reasons.append("NO_SUPPORTING_ACTIVITY")
                reasons.append("NO_DISTANCE_CHANGE")
                reasons.append("NO_RUNTIME_CHANGE")
            elif state_data.last_mowing_attempt_result == "recovery_verified_session":
                reasons.append("RECOVERY_VERIFIED_SESSION")
            elif state_data.last_mowing_attempt_result == "recovery_confirmation_invalid":
                reasons.append("RECOVERY_CONFIRMATION_INVALID")
            elif state_data.last_mowing_attempt_result == "session_lost_offline":
                reasons.append("MOWING_SESSION_LOST_OFFLINE")
            
        if state_data.confirmed_mowing_today:
            reasons.append("CONFIRMED_MOWING_TODAY")
            
        if is_scheduled_now(now):
            if state_data.mowing_attempted_today and not state_data.confirmed_mowing_today:
                reasons.append("MOWING_NOT_CONFIRMED")
                
        if state_data.failed_recovery:
            reasons.append("FAILED_RECOVERY")
            
        if state_data.recovery_state == RecoveryState.RECOVERED:
            reasons.append("RECOVERY_VERIFIED")
            
        _append_pending_reason_codes(reasons, state_data)
        if state_data.distance_reset_count > 0:
            reasons.append("DISTANCE_RESET_DETECTED")
        if state_data.interruption_status is not None:
            norm_status = state_data.interruption_status.strip().lower()
            if norm_status not in ("searching", "detecting status", "unknown"):
                reasons.append("UNKNOWN_SESSION_STATUS")

        # Deduplicate reasons list
        unique_reasons = []
        for r in reasons:
            if r not in unique_reasons:
                unique_reasons.append(r)

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
            "assessment_reasons": unique_reasons,
            "online": state_data.online,
            "last_source_update_at": state_data.last_source_update_at,
            "source_age_minutes": state_data.source_age_minutes,
            "stale_entities": state_data.stale_entities,
            "watchdog_checked_at": self.manager.watchdog_checked_at,
            "source_values_stale": source_values_stale,
            # Schedule properties
            "scheduled_now": is_scheduled_now(now),
            "schedule_start": 11,
            "schedule_end": 18,
            "schedule_timezone": "Europe/Stockholm",
            # Active Mowing Session
            "mowing_session_active": state_data.mowing_session_active,
            "session_started_at": state_data.session_started_at,
            "session_started_source": state_data.session_started_source,
            "session_elapsed_seconds": state_data.session_elapsed_seconds,
            "accumulated_mowing_seconds": state_data.accumulated_mowing_seconds,
            "current_mowing_segment_started_at": state_data.current_mowing_segment_started_at,
            "interruption_started_at": state_data.interruption_started_at,
            "interruption_status": state_data.interruption_status,
            "pending_session_end": state_data.pending_session_end,
            "session_accumulated_positive_distance": state_data.session_accumulated_positive_distance,
            "session_distance_activity_detected": state_data.session_distance_activity_detected,
            "pending_confirmation_ended_at": state_data.pending_confirmation_ended_at,
            "pending_confirmation_mowing_seconds": state_data.pending_confirmation_mowing_seconds,
            "pending_confirmation_session_elapsed_seconds": state_data.pending_confirmation_session_elapsed_seconds,
            "pending_confirmation_distance_activity": state_data.pending_confirmation_distance_activity,
            "pending_confirmation_runtime_activity": state_data.pending_confirmation_runtime_activity,
            "pending_confirmation_battery_activity": state_data.pending_confirmation_battery_activity,
            "pending_confirmation_type": state_data.pending_confirmation_type,
            "distance_reset_count": state_data.distance_reset_count,
            # Last Attempt / Confirmed
            "last_mowing_attempt_at": state_data.last_mowing_attempt_at,
            "last_mowing_attempt_duration_seconds": state_data.last_mowing_attempt_duration_seconds,
            "last_mowing_session_elapsed_seconds": state_data.last_mowing_session_elapsed_seconds,
            "last_mowing_attempt_result": state_data.last_mowing_attempt_result,
            "last_mowing_ended_at": state_data.last_mowing_ended_at,
            "pending_mowing_confirmation": state_data.pending_mowing_confirmation,
            "last_confirmed_mowing_at": state_data.last_confirmed_mowing_at,
            "last_confirmed_mowing_duration_seconds": state_data.last_confirmed_mowing_duration_seconds,
            "confirmed_mowing_today": state_data.confirmed_mowing_today,
            "mowing_attempted_today": state_data.mowing_attempted_today,
            "last_attempt_is_today": attempt_is_today,
            # Supporting activity deltas
            "last_distance_value": state_data.last_distance_value,
            "last_distance_change_at": state_data.last_distance_change_at,
            "last_runtime_hours_value": state_data.last_runtime_hours_value,
            "last_runtime_change_at": state_data.last_runtime_change_at,
            # Recovery
            "failed_recovery": state_data.failed_recovery,
            "recovery_verified_at": state_data.recovery_verified_at,
            "last_real_error_category": state_data.last_real_error_category,
            # Charging trend monitoring
            "charging_started_at": state_data.charging_started_at,
            "charging_last_sample_at": state_data.charging_last_sample_at,
            "charging_last_sample_battery": state_data.charging_last_sample_battery,
            "charging_decline_count": state_data.charging_decline_count,
            "charging_stalled": state_data.charging_stalled,
            "charging_stalled_at": state_data.charging_stalled_at,
            # Daily attention
            "daily_attention_required": state_data.daily_attention_required,
            "daily_attention_state": state_data.daily_attention_state,
            "daily_attention_reason_codes": state_data.daily_attention_reason_codes,
            "daily_attention_text": state_data.daily_attention_text,
            "daily_attention_evaluated_at": state_data.daily_attention_evaluated_at,
            "daily_check_started": self._get_daily_check_started(now),
            "daily_schedule_finished": self._get_daily_schedule_finished(now),
            "daily_observation_complete": self.manager.daily_observation_complete,
        }

    def _get_daily_check_started(self, now: datetime) -> bool:
        from .daily_assessment import daily_check_started
        return daily_check_started(now)

    def _get_daily_schedule_finished(self, now: datetime) -> bool:
        from .daily_assessment import daily_schedule_finished
        return daily_schedule_finished(now)


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

        # Totals for v0.3.0
        robots_mowing_now = 0
        robots_with_active_mowing_session = 0
        robots_confirmed_mowing_today = 0
        robots_with_failed_recovery = 0
        robots_with_pending_confirmation = 0

        # Totals for v0.4.0
        robots_needing_attention = 0
        robots_monitoring = 0
        attention_robot_names = []
        monitoring_robot_names = []

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

            # Mowing session totals
            status_norm = (state_data.current_status_plain or state_data.current_status or "").strip().lower()
            if status_norm == "mowing":
                robots_mowing_now += 1

            if state_data.mowing_session_active:
                robots_with_active_mowing_session += 1
            if state_data.confirmed_mowing_today:
                robots_confirmed_mowing_today += 1
            if state_data.failed_recovery:
                robots_with_failed_recovery += 1
            if state_data.pending_mowing_confirmation:
                robots_with_pending_confirmation += 1

            if state_data.daily_attention_required:
                robots_needing_attention += 1
                attention_robot_names.append(state_data.display_name)
            elif state_data.daily_attention_state == "monitoring":
                robots_monitoring += 1
                monitoring_robot_names.append(state_data.display_name)

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
                # v0.3.0 fields per robot
                "scheduled_now": is_scheduled_now(dt_util.now()),
                "mowing_session_active": state_data.mowing_session_active,
                "confirmed_mowing_today": state_data.confirmed_mowing_today,
                "failed_recovery": state_data.failed_recovery,
                "last_mowing_attempt_result": state_data.last_mowing_attempt_result,
                "pending_mowing_confirmation": state_data.pending_mowing_confirmation,
            }

        total_found = total_expected - total_missing - total_unavailable - total_unknown

        from .daily_assessment import daily_check_started, daily_schedule_finished
        daily_check_started_val = daily_check_started(dt_util.now())
        daily_schedule_finished_val = daily_schedule_finished(dt_util.now())

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
            "robots_mowing_now": robots_mowing_now,
            "robots_with_active_mowing_session": robots_with_active_mowing_session,
            "robots_confirmed_mowing_today": robots_confirmed_mowing_today,
            "robots_with_failed_recovery": robots_with_failed_recovery,
            "robots_with_pending_confirmation": robots_with_pending_confirmation,
            # v0.4.0 metrics
            "robots_needing_attention": robots_needing_attention,
            "robots_monitoring": robots_monitoring,
            "attention_robot_names": attention_robot_names,
            "monitoring_robot_names": monitoring_robot_names,
            "daily_check_started": daily_check_started_val,
            "daily_schedule_finished": daily_schedule_finished_val,
            "last_daily_evaluation_at": self.manager.daily_attention_summary.get("last_evaluated_at"),
            "robots": robots_dict,
        }


class AutomowerSupervisorSummarySensor(SensorEntity):
    """Exposes summary information about robots needing attention."""

    _attr_has_entity_name = True
    _attr_name = "Summary"
    _attr_icon = "mdi:alert-circle-outline"
    _attr_should_poll = False

    def __init__(self, manager: AutomowerSupervisorManager) -> None:
        """Initialize the summary sensor."""
        self.manager = manager
        self.entity_id = "sensor.automower_supervisor_summary"
        self._attr_unique_id = "automower_supervisor_summary"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "global")},
            name="Automower Supervisor",
            manufacturer="Robonect / Husqvarna",
        )

    async def async_added_to_hass(self) -> None:
        """Register callbacks when entity is added to Home Assistant."""
        _LOGGER.debug("Adding summary sensor to hass")
        self.async_on_remove(
            self.manager.async_register_callback(self.async_write_ha_state)
        )

    @property
    def native_value(self) -> int:
        """Return the number of robots needing attention."""
        summary = self.manager.daily_attention_summary
        return summary.get("attention_count", 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details about daily attention states and calendar sync."""
        attrs = dict(self.manager.daily_attention_summary)
        
        # Add calendar sync attributes
        attrs["calendar_sync_enabled"] = self.manager.calendar_enabled
        attrs["calendar_entity_id"] = self.manager.calendar_entity_id
        attrs["last_evening_sync_at"] = self.manager.last_evening_sync_at
        attrs["last_morning_sync_at"] = self.manager.last_morning_sync_at
        attrs["last_calendar_sync_at"] = self.manager.last_calendar_sync_at
        attrs["last_calendar_sync_result"] = self.manager.last_calendar_sync_result
        attrs["last_calendar_sync_error"] = self.manager.last_calendar_sync_error
        
        # Snapshot metadata
        snap = self.manager.calendar_snapshot
        attrs["evening_snapshot_source_date"] = snap.source_date if snap else None
        attrs["evening_snapshot_target_date"] = snap.target_calendar_date if snap else None
        
        from .const import ROBOTS
        evening_names = []
        if snap:
            for r_id in ROBOTS:
                for r in snap.robots:
                    if r.robot_id == r_id:
                        evening_names.append(r.display_name)
                        break
        attrs["evening_snapshot_robot_names"] = evening_names
        
        morning_names = []
        for r_id in ROBOTS:
            if r_id in self.manager.morning_remaining_robot_ids:
                morning_names.append(self.manager.robots[r_id].display_name)
        attrs["morning_remaining_robot_names"] = morning_names
        
        cache = self.manager.event_cache
        attrs["managed_event_date"] = cache.get("date")
        attrs["managed_event_marker"] = cache.get("marker")
        attrs["managed_event_uid"] = cache.get("uid")
        
        title = None

        # Visa endast en titel när integrationen faktiskt har en
        # hanterad kalenderpost kvar i event_cache.
        if cache.get("date"):
            if morning_names:
                title = "Bot " + ", ".join(morning_names)
            elif evening_names:
                title = "Bot " + ", ".join(evening_names)

        attrs["calendar_event_title"] = title
        
        return attrs
