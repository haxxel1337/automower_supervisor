from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any, Callable

from homeassistant.core import HomeAssistant, Event
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
import homeassistant.util.dt as dt_util

import asyncio
from .const import (
    DOMAIN,
    ROBOTS,
    ENTITY_PATTERNS,
    NO_ACTIVE_ERROR_VALUES,
    ERROR_GRACE_PERIOD_MINUTES,
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
    TARGETED_WAKEUP_HOUR,
    TARGETED_WAKEUP_MINUTE,
    MORNING_AUTO_WAIT_SECONDS,
    MORNING_START_WAIT_SECONDS,
    ROBOT_COMMAND_GAP_SECONDS,
    AUTO_RESET_LATCH_MINUTES,
    AUTO_RESET_STEP_DELAY_SECONDS,
    MOWER_DATA_STALE_MINUTES,
    LATE_START_CHECK_HOUR,
    LATE_START_CHECK_MINUTE,
    LATE_START_WINDOW_MINUTES,
    LATE_START_AUTO_WAIT_SECONDS,
    LATE_START_ROBOT_GAP_SECONDS,
)
from .models import RobotState, RecoveryState
from .storage import AutomowerSupervisorStorage
from .error_classifier import classify_error
from .schedule import get_daily_date
from .charging import update_charging_monitor
from .activity import (
    safe_float,
    safe_int,
    update_accumulated_mowing_time,
    update_session_latest_values,
    end_mowing_session,
    check_pending_mowing_confirmation,
    handle_status_change,
    check_daily_rollover,
    update_robot_distance,
    clear_pending_confirmation_fields,
    get_pending_confirmation_age_seconds,
    confirm_pending_mowing,
    fail_pending_mowing_after_error,
)

_LOGGER = logging.getLogger(__name__)


def get_robot_suffix(robot_id: str) -> str:
    """Get the standard entity ID suffix for a robot ID."""
    mapping = {
        "automowerkv5": "kv5",
        "automowertuv4": "tuv4",
        "automowervv14mini": "vv14_mini",
        "automowervv14big": "vv14_big",
        "automowervv18": "vv18",
        "automoweralmv3": "alm_v3",
        "automowerbd17": "bd17",
        "automowersbv14": "sbv14",
        "automowervv2": "vv2",
        "automowertrv4": "trv4",
        "automowerlv9": "lv9",
    }
    return mapping.get(robot_id, robot_id)


def normalize_stored_error_category(
    error_message: str | None,
    stored_category: Any,
) -> tuple[str, bool]:
    """Normalize and backfill error category if missing or invalid.
    
    Returns (normalized_category, is_changed).
    """
    valid_categories = {
        "cutting",
        "movement",
        "communication",
        "other",
        "none",
    }
    
    cat_str = str(stored_category).strip() if stored_category is not None else ""
    cat_lower = cat_str.lower()
    
    # If category is missing or empty or explicitly "none"
    if not cat_str or cat_lower == "none":
        if error_message:
            new_cat = classify_error(error_message)
            is_changed = (stored_category is None or cat_lower != new_cat)
            return new_cat, is_changed
        return "none", (stored_category is not None and cat_lower != "none")
        
    # If the category is invalid
    if cat_lower not in valid_categories:
        if error_message:
            new_cat = classify_error(error_message)
            return new_cat, True
        return "none", True
        
    # If it is valid but has extra spaces or uppercase letters, let's normalize it
    is_changed = (stored_category != cat_lower)
    return cat_lower, is_changed


def _update_entity_state_lists(state: RobotState, entity_id: str, target_list_name: str | None) -> None:
    """Ensure entity_id is mutually exclusive and present in at most one list without duplicates."""
    for lst in (state.missing_entities, state.unavailable_entities, state.unknown_entities):
        if entity_id in lst:
            lst.remove(entity_id)
    if target_list_name == "missing":
        state.missing_entities.append(entity_id)
    elif target_list_name == "unavailable":
        state.unavailable_entities.append(entity_id)
    elif target_list_name == "unknown":
        state.unknown_entities.append(entity_id)


class AutomowerSupervisorManager:
    """Manages tracking and evaluating the state of all configured Automowers."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the manager."""
        self.hass = hass
        self._storage = AutomowerSupervisorStorage(hass)
        self._callbacks: list[Callable[[], None]] = []
        self._unsub_listener: Callable[[], None] | None = None
        self._unsub_watchdog: Callable[[], None] | None = None
        self.watchdog_checked_at: str | None = None
        
        # New for 0.4.0
        self.daily_observation_started_at: str | None = None
        self.daily_tracking_initialized: bool = False
        self.daily_attention_summary: dict[str, Any] = {}

        # New for 0.5.0 (Calendar synchronization properties)
        self.calendar_snapshot = None
        self.event_cache: dict[str, Any] = {}
        self.last_evening_sync_at: str | None = None
        self.last_morning_sync_at: str | None = None
        self.last_calendar_sync_at: str | None = None
        self.last_calendar_sync_result: str | None = None
        self.last_calendar_sync_error: str | None = None
        self.morning_reconciled_at: str | None = None
        self.morning_remaining_robot_ids: list[str] = []
        self.morning_resolved_robot_ids: list[str] = []
        self._calendar_sync_lock = asyncio.Lock()
        self._robot_command_lock = asyncio.Lock()
        self._morning_wakeup_task: asyncio.Task | None = None
        self._auto_reset_tasks: dict[str, asyncio.Task] = {}
        self._late_start_tasks: dict[str, asyncio.Task] = {}
        self._unsub_calendar_timers: list[Callable[[], None]] = []
        
        # Initialize the state representation for all robots
        self.robots: dict[str, RobotState] = {}
        for robot_id, display_name in ROBOTS.items():
            entity_ids = {
                key: pattern.format(robot=robot_id)
                for key, pattern in ENTITY_PATTERNS.items()
            }
            self.robots[robot_id] = RobotState(
                robot_id=robot_id,
                display_name=display_name,
                entity_ids=entity_ids,
            )
            
        # Reverse lookup mapping entity_id to (robot_id, key)
        self._entity_lookup: dict[str, tuple[str, str]] = {}
        for robot_id, state in self.robots.items():
            for key, entity_id in state.entity_ids.items():
                self._entity_lookup[entity_id] = (robot_id, key)

    async def async_setup(self) -> None:
        """Load storage and start tracking entity states."""
        _LOGGER.debug("Setting up Automower Supervisor manager")
        
        # Load from disk
        storage_changed = await self._async_load_storage()
        
        # Initial scan of current state machine states
        if self.sync_initial_states(is_startup=True):
            storage_changed = True
        
        # Set watchdog checked time and calculate metrics directly
        now = dt_util.now()
        self.watchdog_checked_at = now.isoformat()
        for robot_id in self.robots:
            self._update_watchdog_for_robot(robot_id, now)
            
        # Determine tracking initialized/observation started today
        local_date = get_daily_date(now)
        if self.daily_observation_started_at == local_date:
            # We already started tracking today before restart, keep the loaded value
            pass
        else:
            self.daily_observation_started_at = local_date
            from .daily_assessment import daily_check_started
            if not daily_check_started(now):
                self.daily_tracking_initialized = True
            else:
                self.daily_tracking_initialized = False
            storage_changed = True
            
        # Run daily attention assessment
        self.evaluate_all_daily_attention(now)
        
        if storage_changed:
            await self._storage.async_save(self.get_storage_data())
            
        # Register listeners
        self.setup_listeners()

        # Register watchdog timer
        self._unsub_watchdog = async_track_time_interval(
            self.hass,
            self._async_watchdog_check,
            timedelta(minutes=5)
        )

        # Setup calendar timers, missed sync checks and services
        self.setup_calendar_timers()
        self.register_services()
        await self.async_check_missed_syncs()

    async def _async_load_storage(self) -> bool:
        """Load persistent storage and apply it to the robot states. Returns True if storage changed."""
        storage_changed = False
        # Initialize daily_date for all robots first to prevent unwanted first-run save calls
        now = dt_util.now()
        current_date = get_daily_date(now)
        for state in self.robots.values():
            state.daily_date = current_date

        stored_data = await self._storage.async_load()
        if not stored_data:
            _LOGGER.debug("No persistent storage data found")
            return False
            
        _LOGGER.debug("Loading persistent storage data: %s", stored_data)
        
        # Load daily observation metadata
        metadata = stored_data.get("_metadata", {}) if isinstance(stored_data, dict) else {}
        self.daily_observation_started_at = metadata.get("daily_observation_started_at")
        self.daily_tracking_initialized = bool(metadata.get("daily_tracking_initialized", False))

        # Load calendar state from stored data
        calendar_data = stored_data.get("_calendar", {}) if isinstance(stored_data, dict) else {}
        stored_snapshot = calendar_data.get("evening_snapshot")
        self.calendar_snapshot = None
        if stored_snapshot:
            try:
                from .calendar_sync import EveningAttentionSnapshot
                self.calendar_snapshot = EveningAttentionSnapshot.from_dict(stored_snapshot)
            except Exception as err:
                _LOGGER.error("Failed to parse stored evening snapshot: %s", err)

        self.last_evening_sync_at = calendar_data.get("last_evening_sync_at")
        self.last_morning_sync_at = calendar_data.get("last_morning_sync_at")
        self.last_calendar_sync_at = calendar_data.get("last_calendar_sync_at")
        self.last_calendar_sync_result = calendar_data.get("last_calendar_sync_result")
        self.last_calendar_sync_error = calendar_data.get("last_calendar_sync_error")
        self.event_cache = calendar_data.get("event_cache", {})

        for robot_id, data in stored_data.items():
            if robot_id == "_metadata":
                continue
            if robot_id not in self.robots:
                continue
            state = self.robots[robot_id]
            state.last_real_error = data.get("last_real_error")
            state.last_real_error_at = data.get("last_real_error_at")
            state.error_cleared_at = data.get("error_cleared_at")
            state.current_error_active = bool(data.get("current_error_active", False))
            
            # Re-hydrate recovery state safely
            rec_val = data.get("recovery_state", "none")
            try:
                state.recovery_state = RecoveryState(rec_val)
            except ValueError:
                state.recovery_state = RecoveryState.NONE

            state.last_mowing_attempt_at = data.get("last_mowing_attempt_at")
            state.last_mowing_attempt_duration_seconds = data.get("last_mowing_attempt_duration_seconds")
            state.last_mowing_session_elapsed_seconds = data.get("last_mowing_session_elapsed_seconds")
            state.last_mowing_attempt_result = data.get("last_mowing_attempt_result")
            state.last_mowing_ended_at = data.get("last_mowing_ended_at")
            state.last_confirmed_mowing_at = data.get("last_confirmed_mowing_at")
            state.last_confirmed_mowing_duration_seconds = data.get("last_confirmed_mowing_duration_seconds")
            state.last_distance_value = data.get("last_distance_value")
            state.last_distance_change_at = data.get("last_distance_change_at")
            state.last_runtime_hours_value = data.get("last_runtime_hours_value")
            state.last_runtime_change_at = data.get("last_runtime_change_at")
            state.confirmed_mowing_today = bool(data.get("confirmed_mowing_today", False))
            state.mowing_attempted_today = bool(data.get("mowing_attempted_today", False))
            state.failed_recovery = bool(data.get("failed_recovery", False))
            state.recovery_verified_at = data.get("recovery_verified_at")
            state.morning_wakeup_attempted_date = data.get("morning_wakeup_attempted_date")
            state.morning_wakeup_attempted_at = data.get("morning_wakeup_attempted_at")
            state.morning_wakeup_result = data.get("morning_wakeup_result")
            state.morning_wakeup_stage = data.get("morning_wakeup_stage")
            state.auto_reset_attempted_at = data.get("auto_reset_attempted_at")
            state.auto_reset_incident_at = data.get("auto_reset_incident_at")
            state.auto_reset_error_message = data.get("auto_reset_error_message")
            state.auto_reset_result = data.get("auto_reset_result")
            state.auto_reset_stage = data.get("auto_reset_stage")
            state.auto_reset_in_progress = False
            
            # Backfill and normalize error category
            stored_category = data.get("last_real_error_category")
            normalized_cat, is_changed = normalize_stored_error_category(
                state.last_real_error,
                stored_category,
            )
            state.last_real_error_category = normalized_cat
            if is_changed:
                storage_changed = True
            
            state.pending_mowing_confirmation = bool(data.get("pending_mowing_confirmation", False))
            state.pending_confirmation_ended_at = data.get("pending_confirmation_ended_at")
            state.pending_confirmation_mowing_seconds = int(data.get("pending_confirmation_mowing_seconds", 0))
            state.pending_confirmation_session_elapsed_seconds = int(data.get("pending_confirmation_session_elapsed_seconds", 0))
            state.pending_confirmation_distance_activity = bool(data.get("pending_confirmation_distance_activity", False))
            state.pending_confirmation_runtime_activity = bool(data.get("pending_confirmation_runtime_activity", False))
            state.pending_confirmation_battery_activity = bool(data.get("pending_confirmation_battery_activity", False))
            p_type = data.get("pending_confirmation_type")
            if state.pending_mowing_confirmation:
                if p_type is None:
                    mow_secs = state.pending_confirmation_mowing_seconds
                    if mow_secs >= 600:
                        state.pending_confirmation_type = "full_mowing"
                    elif state.recovery_state == RecoveryState.CLEARED_BUT_UNVERIFIED:
                        state.pending_confirmation_type = "recovery_only"
                    else:
                        _LOGGER.info("Old pending confirmation type not found for robot %s. Falling back to full_mowing.", robot_id)
                        state.pending_confirmation_type = "full_mowing"
                    storage_changed = True
                elif p_type not in ("full_mowing", "recovery_only"):
                    _LOGGER.warning("Invalid pending confirmation type '%s' for robot %s. Normalizing to full_mowing.", p_type, robot_id)
                    state.pending_confirmation_type = "full_mowing"
                    storage_changed = True
                else:
                    state.pending_confirmation_type = p_type
            else:
                if p_type is not None:
                    state.pending_confirmation_type = None
                    storage_changed = True
                else:
                    state.pending_confirmation_type = None
            
            state.recovery_distance_baseline = data.get("recovery_distance_baseline")
            state.recovery_accumulated_positive_distance = float(data.get("recovery_accumulated_positive_distance", 0.0))
            state.recovery_previous_distance = data.get("recovery_previous_distance")

            state.charging_started_at = data.get("charging_started_at")
            state.charging_last_sample_at = data.get("charging_last_sample_at")
            state.charging_last_sample_battery = data.get("charging_last_sample_battery")
            state.charging_decline_count = int(data.get("charging_decline_count", 0))
            state.charging_stalled = bool(data.get("charging_stalled", False))
            state.charging_stalled_at = data.get("charging_stalled_at")
            
            if "daily_date" in data and data["daily_date"] is not None:
                state.daily_date = data["daily_date"]

        return storage_changed

    def get_storage_data(self) -> dict[str, Any]:
        """Return a dictionary of serializable state information to store on disk."""
        data = {}
        for robot_id, state in self.robots.items():
            data[robot_id] = {
                "last_real_error": state.last_real_error,
                "last_real_error_at": state.last_real_error_at,
                "error_cleared_at": state.error_cleared_at,
                "current_error_active": state.current_error_active,
                "recovery_state": str(state.recovery_state.value),
                "last_mowing_attempt_at": state.last_mowing_attempt_at,
                "last_mowing_attempt_duration_seconds": state.last_mowing_attempt_duration_seconds,
                "last_mowing_session_elapsed_seconds": state.last_mowing_session_elapsed_seconds,
                "last_mowing_attempt_result": state.last_mowing_attempt_result,
                "last_mowing_ended_at": state.last_mowing_ended_at,
                "last_confirmed_mowing_at": state.last_confirmed_mowing_at,
                "last_confirmed_mowing_duration_seconds": state.last_confirmed_mowing_duration_seconds,
                "last_distance_value": state.last_distance_value,
                "last_distance_change_at": state.last_distance_change_at,
                "last_runtime_hours_value": state.last_runtime_hours_value,
                "last_runtime_change_at": state.last_runtime_change_at,
                "confirmed_mowing_today": state.confirmed_mowing_today,
                "mowing_attempted_today": state.mowing_attempted_today,
                "failed_recovery": state.failed_recovery,
                "recovery_verified_at": state.recovery_verified_at,
                "last_real_error_category": state.last_real_error_category,
                "morning_wakeup_attempted_date": state.morning_wakeup_attempted_date,
                "morning_wakeup_attempted_at": state.morning_wakeup_attempted_at,
                "morning_wakeup_result": state.morning_wakeup_result,
                "morning_wakeup_stage": state.morning_wakeup_stage,
                "auto_reset_attempted_at": state.auto_reset_attempted_at,
                "auto_reset_incident_at": state.auto_reset_incident_at,
                "auto_reset_error_message": state.auto_reset_error_message,
                "auto_reset_result": state.auto_reset_result,
                "auto_reset_stage": state.auto_reset_stage,
                "pending_mowing_confirmation": state.pending_mowing_confirmation,
                "pending_confirmation_ended_at": state.pending_confirmation_ended_at,
                "pending_confirmation_mowing_seconds": state.pending_confirmation_mowing_seconds,
                "pending_confirmation_session_elapsed_seconds": state.pending_confirmation_session_elapsed_seconds,
                "pending_confirmation_distance_activity": state.pending_confirmation_distance_activity,
                "pending_confirmation_runtime_activity": state.pending_confirmation_runtime_activity,
                "pending_confirmation_battery_activity": state.pending_confirmation_battery_activity,
                "pending_confirmation_type": state.pending_confirmation_type,
                "recovery_distance_baseline": state.recovery_distance_baseline,
                "recovery_accumulated_positive_distance": state.recovery_accumulated_positive_distance,
                "recovery_previous_distance": state.recovery_previous_distance,
                "charging_started_at": state.charging_started_at,
                "charging_last_sample_at": state.charging_last_sample_at,
                "charging_last_sample_battery": state.charging_last_sample_battery,
                "charging_decline_count": state.charging_decline_count,
                "charging_stalled": state.charging_stalled,
                "charging_stalled_at": state.charging_stalled_at,
                "daily_date": state.daily_date,
            }
        data["_metadata"] = {
            "daily_observation_started_at": self.daily_observation_started_at,
            "daily_tracking_initialized": self.daily_tracking_initialized,
        }
        data["_calendar"] = {
            "calendar_entity_id": self.calendar_entity_id,
            "evening_snapshot": self.calendar_snapshot.to_dict() if self.calendar_snapshot else None,
            "event_cache": self.event_cache,
            "last_evening_sync_at": self.last_evening_sync_at,
            "last_morning_sync_at": self.last_morning_sync_at,
            "last_calendar_sync_at": self.last_calendar_sync_at,
            "last_calendar_sync_result": self.last_calendar_sync_result,
            "last_calendar_sync_error": self.last_calendar_sync_error,
        }
        return data

    def sync_initial_states(self, is_startup: bool = False) -> bool:
        """Sync initial states of entities from Home Assistant."""
        now = dt_util.now()
        current_time_iso = now.isoformat()
        storage_changed = False
        
        for robot_id, state in self.robots.items():
            # Check daily rollover first
            if check_daily_rollover(state, now):
                storage_changed = True

            # Clear discovery lists for initial scan
            state.missing_entities.clear()
            state.unavailable_entities.clear()
            state.unknown_entities.clear()
            
            for key, entity_id in state.entity_ids.items():
                ha_state = self.hass.states.get(entity_id)
                
                if ha_state is None:
                    _update_entity_state_lists(state, entity_id, "missing")
                    self._update_state_field(state, key, None)
                elif ha_state.state == "unavailable":
                    _update_entity_state_lists(state, entity_id, "unavailable")
                    self._update_state_field(state, key, None)
                elif ha_state.state == "unknown":
                    _update_entity_state_lists(state, entity_id, "unknown")
                    self._update_state_field(state, key, None)
                else:
                    _update_entity_state_lists(state, entity_id, None)
                    self._update_state_field(state, key, ha_state.state)
                    
            # Update charging trend after status and battery are loaded
            if update_charging_monitor(state, now):
                storage_changed = True

            # Evaluate error state after initial loading
            if self._update_robot_error_state(robot_id, current_time_iso):
                storage_changed = True

            # Check pending mowing confirmation
            if state.pending_mowing_confirmation:
                if check_pending_mowing_confirmation(state, now):
                    storage_changed = True

            # Handle HA restart during Mowing
            if is_startup:
                status_norm = (state.current_status_plain or state.current_status or "").strip().lower()
                if status_norm == "mowing" and not state.mowing_session_active:
                    state.mowing_session_active = True
                    state.session_started_at = dt_util.as_utc(now).isoformat()
                    state.session_started_source = "startup_observation"
                    state.current_mowing_segment_started_at = dt_util.as_utc(now).isoformat()
                    state.accumulated_mowing_seconds = 0
                    state.session_elapsed_seconds = 0
                    
                    state.session_start_battery = state.current_battery
                    state.session_start_distance = state.last_distance_value
                    state.session_start_runtime_hours = state.last_runtime_hours_value
                    
                    state.session_latest_battery = state.current_battery
                    state.session_latest_distance = state.last_distance_value
                    state.session_latest_runtime_hours = state.last_runtime_hours_value
                    
                    state.session_error_detected = False
                    state.session_binary_error_detected = False
                    state.pending_session_end = False
                    
                    state.mowing_attempted_today = True
                    storage_changed = True

        return storage_changed

    def setup_listeners(self) -> None:
        """Setup listeners for state change events."""
        # Listen to all entities we are tracking
        all_entity_ids = list(self._entity_lookup.keys())
        _LOGGER.debug("Registering event tracking for %d entities", len(all_entity_ids))
        
        self._unsub_listener = async_track_state_change_event(
            self.hass,
            all_entity_ids,
            self._async_state_changed_event
        )

    async def _async_state_changed_event(self, event: Event) -> None:
        """Handle state change event."""
        entity_id = event.data.get("entity_id")
        if not entity_id:
            return
            
        new_state = event.data.get("new_state")
        
        # Lookup which robot and key this corresponds to
        lookup = self._entity_lookup.get(entity_id)
        if not lookup:
            return
            
        robot_id, key = lookup
        state = self.robots[robot_id]
        
        current_time_iso = dt_util.now().isoformat()
        state.last_event_at = current_time_iso
        
        now = dt_util.now()
        storage_changed = check_daily_rollover(state, now)
        
        if state.mowing_session_active:
            update_accumulated_mowing_time(state, now)
        
        # Update lists and state values
        if new_state is None:
            _update_entity_state_lists(state, entity_id, "missing")
            if self._update_state_field(state, key, None):
                storage_changed = True
        elif new_state.state == "unavailable":
            _update_entity_state_lists(state, entity_id, "unavailable")
            if self._update_state_field(state, key, None):
                storage_changed = True
        elif new_state.state == "unknown":
            _update_entity_state_lists(state, entity_id, "unknown")
            if self._update_state_field(state, key, None):
                storage_changed = True
        else:
            _update_entity_state_lists(state, entity_id, None)
            if self._update_state_field(state, key, new_state.state):
                storage_changed = True
                
        # If status changed, handle session state machine
        if key in ("status_plain", "status"):
            status_val = state.current_status_plain or state.current_status
            if handle_status_change(state, status_val, now):
                storage_changed = True
                
        # Update watchdog metrics in real-time
        self._update_watchdog_for_robot(robot_id, now)

        # Update charging trend after source-state changes
        if update_charging_monitor(state, now):
            storage_changed = True
            
        # Re-evaluate logic for errors
        if self._update_robot_error_state(robot_id, current_time_iso):
            storage_changed = True
            
        if storage_changed:
            _LOGGER.debug("Data changed for %s, saving/scheduling save to storage", robot_id)
            self._storage.async_delay_save(self.get_storage_data, 10.0)
            
        # Run daily attention assessment (which also notifies callbacks)
        self.evaluate_all_daily_attention(now)

    def _update_state_field(self, state: RobotState, key: str, value: str | None) -> bool:
        """Update the real-time field based on the entity key. Returns True if storage changed."""
        storage_changed = False
        if key == "status":
            state.current_status = value
        elif key == "status_plain":
            state.current_status_plain = value
        elif key == "battery":
            val_int = safe_int(value)
            state.current_battery = val_int
            if state.mowing_session_active:
                state.session_latest_battery = val_int
                if state.session_start_battery is None:
                    state.session_start_battery = val_int
        elif key == "error_message":
            state.current_error_message = value
        elif key == "error_binary":
            state.binary_error = value
            if value == "on":
                if state.mowing_session_active:
                    state.session_binary_error_detected = True
        elif key == "distance":
            val_float = safe_float(value)
            if update_robot_distance(state, val_float):
                storage_changed = True
        elif key == "statistic_hours":
            val_float = safe_float(value)
            if state.mowing_session_active:
                state.session_latest_runtime_hours = val_float
                if state.session_start_runtime_hours is None:
                    state.session_start_runtime_hours = val_float
            if val_float is not None and val_float != state.last_runtime_hours_value:
                state.last_runtime_hours_value = val_float
                state.last_runtime_change_at = dt_util.as_utc(dt_util.now()).isoformat()
                storage_changed = True
                
        return storage_changed

    def _update_robot_error_state(self, robot_id: str, current_time_iso: str) -> bool:
        """Evaluate the robot error state machine. Returns True if storage fields changed."""
        state = self.robots[robot_id]
        was_error_active = state.current_error_active
        
        # Normalise error message
        is_real_error = False
        if state.current_error_message:
            norm = state.current_error_message.strip().lower()
            if norm and norm not in NO_ACTIVE_ERROR_VALUES:
                is_real_error = True
                
        is_binary_error = state.binary_error == "on"
        current_active = is_real_error or is_binary_error
        
        changed = False
        
        if current_active:
            # Evaluate pending mowing confirmation on error first
            if state.pending_mowing_confirmation:
                if not state.pending_confirmation_ended_at:
                    _LOGGER.warning(
                        "Robot %s has pending_mowing_confirmation but pending_confirmation_ended_at is missing. Clearing corrupt state on error.",
                        state.robot_id,
                    )
                    clear_pending_confirmation_fields(state)
                    changed = True
                else:
                    try:
                        now_dt = datetime.fromisoformat(current_time_iso)
                        age = get_pending_confirmation_age_seconds(state, now_dt)
                        if age is None:
                            clear_pending_confirmation_fields(state)
                            changed = True
                        elif age >= ERROR_GRACE_PERIOD_MINUTES * 60:
                            # Confirm pending candidate first, then treat this as a new error
                            if confirm_pending_mowing(state, now_dt):
                                changed = True
                        else:
                            # Within grace period, fail it
                            if fail_pending_mowing_after_error(state):
                                changed = True
                    except Exception as err:
                        _LOGGER.error("Error evaluating pending confirmation age on error: %s", err)
                        clear_pending_confirmation_fields(state)
                        changed = True

            # Then process the new active error
            if not state.current_error_active:
                state.current_error_active = True
                changed = True
            if state.recovery_state != RecoveryState.ACTIVE_ERROR:
                if state.recovery_state == RecoveryState.CLEARED_BUT_UNVERIFIED:
                    state.failed_recovery = True
                state.recovery_state = RecoveryState.ACTIVE_ERROR
                changed = True
            if state.error_cleared_at is not None:
                state.error_cleared_at = None
                changed = True
                
            if is_real_error:
                # Update timestamp ONLY if we are transitioning to active or the error text changed
                if not was_error_active or state.last_real_error != state.current_error_message:
                    state.last_real_error = state.current_error_message
                    state.last_real_error_at = current_time_iso
                    state.last_real_error_category = classify_error(state.current_error_message)
                    changed = True

            # If there is an active session, mark error detected
            if state.mowing_session_active:
                if is_real_error:
                    state.session_error_detected = True
                if is_binary_error:
                    state.session_binary_error_detected = True
        else:
            # No active error reported by sensors
            if state.recovery_state == RecoveryState.ACTIVE_ERROR:
                state.current_error_active = False
                state.recovery_state = RecoveryState.CLEARED_BUT_UNVERIFIED
                state.error_cleared_at = current_time_iso
                
                # Initialize recovery distance tracking
                state.recovery_distance_baseline = state.last_distance_value
                state.recovery_previous_distance = state.last_distance_value
                state.recovery_accumulated_positive_distance = 0.0
                
                changed = True
            else:
                # Keep cleared_but_unverified state. Ensure current_error_active is sync'd to False.
                if state.current_error_active:
                    state.current_error_active = False
                    changed = True
                    
        return changed

    @staticmethod
    def _robonect_button_ids(robot_id: str) -> dict[str, str]:
        """Return the Robonect command button IDs for one robot."""
        return {
            "auto": f"button.{robot_id}_auto",
            "start": f"button.{robot_id}_start",
            "stop": f"button.{robot_id}_stop",
            "error_reset": f"button.{robot_id}_error_reset",
        }

    def _button_available(self, entity_id: str) -> bool:
        """Return whether a Robonect button entity is available."""
        entity_state = self.hass.states.get(entity_id)
        return entity_state is not None and entity_state.state not in (
            "unknown",
            "unavailable",
        )

    async def _async_press_robonect_button(self, entity_id: str) -> None:
        """Queue a Robonect button press without blocking on its REST request."""
        if not self._button_available(entity_id):
            raise RuntimeError(f"Button unavailable: {entity_id}")
        await self.hass.services.async_call(
            "button",
            "press",
            {"entity_id": entity_id},
            blocking=False,
        )

    @staticmethod
    def _resting_status(state: RobotState) -> bool:
        """Return whether a healthy robot is stationary and may need waking."""
        status = (
            state.current_status_plain or state.current_status or ""
        ).strip().lower()
        return status in {"charging", "parked", "sleeping", "stopped", "off"}

    def _targeted_wakeup_eligible(self, state: RobotState, local_date: str) -> bool:
        """Return whether one robot may receive the 09:00 wake-up sequence."""
        if state.morning_wakeup_attempted_date == local_date:
            return False
        if state.online is not True:
            return False
        if state.source_age_minutes is None or state.source_age_minutes > 15:
            return False
        if state.current_error_active or state.binary_error == "on":
            return False
        if state.recovery_state == RecoveryState.ACTIVE_ERROR:
            return False
        return self._resting_status(state)

    async def _async_run_targeted_morning_wakeup(
        self,
        now: datetime | None = None,
    ) -> None:
        """Wake only eligible resting robots, one at a time."""
        from .calendar_sync import get_stockholm_timezone

        local_now = (now or dt_util.now()).astimezone(get_stockholm_timezone())
        local_date = local_now.date().isoformat()

        async with self._robot_command_lock:
            for robot_id, state in self.robots.items():
                if not self._targeted_wakeup_eligible(state, local_date):
                    continue

                buttons = self._robonect_button_ids(robot_id)
                state.morning_wakeup_attempted_date = local_date
                state.morning_wakeup_attempted_at = dt_util.as_utc(local_now).isoformat()
                state.morning_wakeup_stage = "auto"
                state.morning_wakeup_result = "in_progress"
                await self._storage.async_save(self.get_storage_data())
                self._notify_callbacks()

                try:
                    await self._async_press_robonect_button(buttons["auto"])
                    await asyncio.sleep(MORNING_AUTO_WAIT_SECONDS)

                    self.sync_initial_states(is_startup=False)
                    if self._resting_status(state):
                        state.morning_wakeup_stage = "start"
                        await self._async_press_robonect_button(buttons["start"])
                        await asyncio.sleep(MORNING_START_WAIT_SECONDS)

                        state.morning_wakeup_stage = "auto_after_start"
                        await self._async_press_robonect_button(buttons["auto"])
                        state.morning_wakeup_result = "auto_start_auto_sent"
                    else:
                        state.morning_wakeup_result = "auto_was_sufficient"

                    state.morning_wakeup_stage = "complete"
                except Exception as err:
                    _LOGGER.error(
                        "Targeted morning wake-up failed for %s at %s: %s",
                        robot_id,
                        state.morning_wakeup_stage,
                        err,
                    )
                    state.morning_wakeup_result = f"command_error: {err}"
                finally:
                    await self._storage.async_save(self.get_storage_data())
                    self._notify_callbacks()

                await asyncio.sleep(ROBOT_COMMAND_GAP_SECONDS)

    def _latched_error_reset_eligible(self, state: RobotState, now: datetime) -> bool:
        """Return True only for stale error text while already mowing."""
        if state.auto_reset_in_progress:
            return False
        if state.current_error_active is not True:
            return False
        if state.binary_error != "off":
            return False
        if state.online is not True:
            return False
        if state.source_age_minutes is None or state.source_age_minutes > 15:
            return False

        status = (
            state.current_status_plain or state.current_status or ""
        ).strip().lower()
        if status != "mowing":
            return False

        error_text = (state.current_error_message or "").strip()
        if not error_text or error_text.lower() in NO_ACTIVE_ERROR_VALUES:
            return False

        incident_at = state.last_real_error_at
        if not incident_at or state.auto_reset_incident_at == incident_at:
            return False

        try:
            incident_dt = datetime.fromisoformat(incident_at)
            age = (
                dt_util.as_utc(now) - dt_util.as_utc(incident_dt)
            ).total_seconds()
        except (TypeError, ValueError):
            return False

        return age >= AUTO_RESET_LATCH_MINUTES * 60

    async def _async_run_latched_error_reset(self, robot_id: str, now: datetime) -> None:
        """Run STOP -> RESET -> START -> AUTO for one eligible mower."""
        state = self.robots[robot_id]

        async with self._robot_command_lock:
            if not self._latched_error_reset_eligible(state, now):
                return

            buttons = self._robonect_button_ids(robot_id)
            state.auto_reset_in_progress = True
            state.auto_reset_attempted_at = dt_util.as_utc(now).isoformat()
            state.auto_reset_incident_at = state.last_real_error_at
            state.auto_reset_error_message = state.current_error_message
            state.auto_reset_result = "in_progress"
            state.auto_reset_stage = "stop"
            await self._storage.async_save(self.get_storage_data())
            self._notify_callbacks()

            try:
                await self._async_press_robonect_button(buttons["stop"])
                await asyncio.sleep(AUTO_RESET_STEP_DELAY_SECONDS)

                state.auto_reset_stage = "error_reset"
                await self._async_press_robonect_button(buttons["error_reset"])
                await asyncio.sleep(AUTO_RESET_STEP_DELAY_SECONDS)

                state.auto_reset_stage = "start"
                await self._async_press_robonect_button(buttons["start"])
                await asyncio.sleep(AUTO_RESET_STEP_DELAY_SECONDS)

                state.auto_reset_stage = "auto"
                await self._async_press_robonect_button(buttons["auto"])

                state.auto_reset_stage = "complete"
                state.auto_reset_result = "commands_sent_awaiting_verification"
            except Exception as err:
                _LOGGER.error(
                    "Latched-error reset failed for %s at %s: %s",
                    robot_id,
                    state.auto_reset_stage,
                    err,
                )
                state.auto_reset_result = f"command_error: {err}"
            finally:
                state.auto_reset_in_progress = False
                await self._storage.async_save(self.get_storage_data())
                self._notify_callbacks()

    def _schedule_latched_error_reset_if_needed(
        self,
        robot_id: str,
        now: datetime,
    ) -> bool:
        """Schedule one reset task without blocking the watchdog."""
        state = self.robots[robot_id]
        task = self._auto_reset_tasks.get(robot_id)
        if task is not None and not task.done():
            return False
        if not self._latched_error_reset_eligible(state, now):
            return False

        task = self.hass.async_create_task(
            self._async_run_latched_error_reset(robot_id, now)
        )
        self._auto_reset_tasks[robot_id] = task
        return True

    def _late_start_check_window_active(self, now: datetime) -> bool:
        # Return True during the late scheduled-start check window.
        from .calendar_sync import get_stockholm_timezone

        local_now = now.astimezone(get_stockholm_timezone())
        minutes = local_now.hour * 60 + local_now.minute
        start = LATE_START_CHECK_HOUR * 60 + LATE_START_CHECK_MINUTE
        return start <= minutes < start + LATE_START_WINDOW_MINUTES

    def _late_start_kick_eligible(self, state: RobotState, now: datetime) -> bool:
        # Return whether a robot should receive AUTO -> START after schedule start.
        if not self._late_start_check_window_active(now):
            return False

        local_date = get_daily_date(now)
        if state.late_start_attempted_date == local_date:
            return False
        if state.online is not True:
            return False
        if state.source_age_minutes is None or state.source_age_minutes > 15:
            return False
        if getattr(state, "mower_data_stale", False):
            return False
        if state.current_error_active or state.binary_error == "on":
            return False
        if state.recovery_state in (
            RecoveryState.ACTIVE_ERROR,
            RecoveryState.CLEARED_BUT_UNVERIFIED,
        ):
            return False
        if state.failed_recovery:
            return False
        if state.confirmed_mowing_today or state.mowing_attempted_today:
            return False
        if state.mowing_session_active or state.pending_mowing_confirmation:
            return False
        return self._resting_status(state)

    async def _async_run_late_start_kick(self, robot_id: str, now: datetime) -> None:
        # Send AUTO then START to one healthy resting robot after schedule start.
        state = self.robots[robot_id]
        local_date = get_daily_date(now)
        buttons = self._robonect_button_ids(robot_id)

        async with self._robot_command_lock:
            if not self._late_start_kick_eligible(state, dt_util.now()):
                return

            state.late_start_attempted_date = local_date
            state.late_start_attempted_at = dt_util.as_utc(now).isoformat()
            state.late_start_stage = "auto"
            state.late_start_result = "in_progress"
            await self._storage.async_save(self.get_storage_data())
            self._notify_callbacks()

            try:
                await self._async_press_robonect_button(buttons["auto"])
                await asyncio.sleep(LATE_START_AUTO_WAIT_SECONDS)

                self.sync_initial_states(is_startup=False)
                if self._resting_status(state) and not state.mowing_attempted_today:
                    state.late_start_stage = "start"
                    await self._async_press_robonect_button(buttons["start"])
                    state.late_start_result = "auto_start_sent"
                else:
                    state.late_start_result = "auto_was_sufficient"

                state.late_start_stage = "complete"
            except Exception as err:
                _LOGGER.error(
                    "Late start kick failed for %s at %s: %s",
                    robot_id,
                    state.late_start_stage,
                    err,
                )
                state.late_start_result = f"command_error: {err}"
            finally:
                await self._storage.async_save(self.get_storage_data())
                self._notify_callbacks()

            await asyncio.sleep(LATE_START_ROBOT_GAP_SECONDS)

    def _schedule_late_start_kick_if_needed(self, robot_id: str, now: datetime) -> bool:
        # Schedule one late start task without blocking the watchdog.
        state = self.robots[robot_id]
        task = self._late_start_tasks.get(robot_id)
        if task is not None and not task.done():
            return False
        if not self._late_start_kick_eligible(state, now):
            return False

        task = self.hass.async_create_task(self._async_run_late_start_kick(robot_id, now))
        self._late_start_tasks[robot_id] = task
        return True

    async def _async_service_window_reconciliation_tick(self, now: datetime) -> None:
        """Reconcile calendar every five minutes from 11:20 through 12:15."""
        from .calendar_sync import get_stockholm_timezone, is_service_day

        local_now = now.astimezone(get_stockholm_timezone())
        if not is_service_day(local_now.date()):
            return

        minutes = local_now.hour * 60 + local_now.minute
        if 11 * 60 + 20 <= minutes <= 12 * 60 + 15:
            await self.async_run_morning_calendar_sync(local_now)

    def async_register_callback(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register a callback for update notifications."""
        if callback not in self._callbacks:
            self._callbacks.append(callback)
            
        def _unsubscribe() -> None:
            if callback in self._callbacks:
                self._callbacks.remove(callback)
                
        return _unsubscribe

    def _notify_callbacks(self) -> None:
        """Notify all registered sensor callbacks."""
        for callback in list(self._callbacks):
            try:
                callback()
            except Exception as err:
                _LOGGER.error("Failed to run state change callback: %s", err)

    async def async_unload(self) -> None:
        """Unload entry, clear listeners and save immediately."""
        _LOGGER.debug("Unloading Automower Supervisor manager")
        if self._unsub_listener:
            try:
                self._unsub_listener()
            except Exception as err:
                _LOGGER.error("Error unsubscribing state listener: %s", err)
            self._unsub_listener = None
            
        if self._unsub_watchdog:
            try:
                self._unsub_watchdog()
            except Exception as err:
                _LOGGER.error("Error unsubscribing watchdog timer: %s", err)
            self._unsub_watchdog = None

        if self._morning_wakeup_task is not None and not self._morning_wakeup_task.done():
            self._morning_wakeup_task.cancel()
        self._morning_wakeup_task = None

        for task in self._auto_reset_tasks.values():
            if not task.done():
                task.cancel()
        self._auto_reset_tasks.clear()

        for task in self._late_start_tasks.values():
            if not task.done():
                task.cancel()
        self._late_start_tasks.clear()

        # Unsubscribe calendar timers
        for unsub in self._unsub_calendar_timers:
            try:
                unsub()
            except Exception as err:
                _LOGGER.error("Error unsubscribing calendar timer: %s", err)
        self._unsub_calendar_timers.clear()

        # Remove registered services
        try:
            self.hass.services.async_remove(DOMAIN, "sync_calendar")
            self.hass.services.async_remove(DOMAIN, "delete_managed_calendar_event")
        except Exception as err:
            _LOGGER.error("Error removing services: %s", err)
            
        # Clear callbacks
        self._callbacks.clear()
            
        # Write storage synchronously/immediately before unload completes
        await self._storage.async_save(self.get_storage_data())

    def _update_watchdog_for_robot(self, robot_id: str, now: datetime) -> None:
        """Calculate and update state age/online watchdog metrics for a single robot."""
        state = self.robots[robot_id]
        
        HEARTBEAT_KEYS = [
            "clock",
            "status",
            "status_plain",
            "battery",
            "error_message",
            "error_binary",
            "distance",
            "statistic_hours",
        ]
        
        existing_heartbeats = []
        useful_heartbeats = []
        
        for key in HEARTBEAT_KEYS:
            entity_id = state.entity_ids.get(key)
            if not entity_id:
                continue
            ha_state = self.hass.states.get(entity_id)
            if ha_state is not None:
                existing_heartbeats.append(ha_state)
                if ha_state.state not in ("unavailable", "unknown"):
                    useful_heartbeats.append((entity_id, ha_state))
                    
        state.stale_entities.clear()
        
        if useful_heartbeats:
            # Find latest useful update
            latest_ha_state = max(useful_heartbeats, key=lambda item: item[1].last_updated)[1]
            latest_dt = latest_ha_state.last_updated
            state.last_source_update_at = latest_dt.isoformat()
            state.last_heartbeat_seen_at = latest_dt.isoformat()
            
            now_utc = dt_util.as_utc(now)
            latest_utc = dt_util.as_utc(latest_dt)
            
            age_delta = now_utc - latest_utc
            age_min = max(0, int(age_delta.total_seconds() / 60))
            state.source_age_minutes = age_min
            
            # online classification
            if age_min <= 15:
                state.online = True
            elif age_min > 60:
                state.online = False
            else:
                state.online = True  # stale/warning but not definitely offline
                
            # Check for individual stale entities (age > 15 minutes)
            for entity_id, ha_state in useful_heartbeats:
                entity_age = (
                    dt_util.as_utc(now) - dt_util.as_utc(ha_state.last_updated)
                ).total_seconds() / 60
                if entity_age > 15:
                    state.stale_entities.append(entity_id)
        else:
            # No useful heartbeats currently available
            if state.last_heartbeat_seen_at is not None:
                # Use the previously seen heartbeat time
                seen_dt = datetime.fromisoformat(state.last_heartbeat_seen_at)
                
                now_utc = dt_util.as_utc(now)
                seen_utc = dt_util.as_utc(seen_dt)
                
                age_delta = now_utc - seen_utc
                age_min = max(0, int(age_delta.total_seconds() / 60))
                state.source_age_minutes = age_min
                
                if age_min <= 15:
                    state.online = True
                elif age_min > 60:
                    state.online = False
                else:
                    state.online = True
            else:
                state.online = None
                state.source_age_minutes = None

        # Separate mower-data freshness from Robonect heartbeat/clock freshness.
        # Clock can keep ticking while important mower values are stale.
        mower_data_keys = [
            "status",
            "status_plain",
            "battery",
            "error_message",
            "distance",
            "statistic_hours",
        ]
        useful_mower_data = []
        for key in mower_data_keys:
            entity_id = state.entity_ids.get(key)
            if not entity_id:
                continue
            ha_state = self.hass.states.get(entity_id)
            if ha_state is not None and ha_state.state not in ("unavailable", "unknown"):
                useful_mower_data.append((entity_id, ha_state))

        if useful_mower_data:
            latest_mower_state = max(
                useful_mower_data,
                key=lambda item: item[1].last_updated,
            )[1]
            mower_age_delta = (
                dt_util.as_utc(now) - dt_util.as_utc(latest_mower_state.last_updated)
            )
            state.mower_data_age_minutes = max(
                0,
                int(mower_age_delta.total_seconds() / 60),
            )
            state.mower_data_stale = (
                state.mower_data_age_minutes > MOWER_DATA_STALE_MINUTES
            )
        else:
            state.mower_data_age_minutes = None
            state.mower_data_stale = True

    async def _async_watchdog_check(self, now: datetime) -> None:
        """Run periodic watchdog evaluation for all robots."""
        _LOGGER.debug("Running periodic watchdog check")
        self.watchdog_checked_at = now.isoformat()
        
        # Sync states for all robots to ensure we have the absolute latest states from HA
        storage_changed = self.sync_initial_states(is_startup=False)
        
        # Update watchdog metrics and perform session/interruption checks for all robots
        for robot_id, state in self.robots.items():
            self._update_watchdog_for_robot(robot_id, now)
            
            # Daily rollover
            if check_daily_rollover(state, now):
                storage_changed = True
                
            # If session is active:
            if state.mowing_session_active:
                update_accumulated_mowing_time(state, now)
                update_session_latest_values(state)
                
                # Safeguard: if robot goes offline, end session
                if state.online is False:
                    if end_mowing_session(state, now, "session_lost_offline"):
                        storage_changed = True
                else:
                    status_norm = (state.current_status_plain or state.current_status or "").strip().lower()
                        
                    terminating_statuses = {
                        "error", "fault", "charging", "sleeping", "parked", 
                        "way home", "searching for charging station", "stopped", "off"
                    }
                    if status_norm in terminating_statuses:
                        if status_norm in ("error", "fault"):
                            state.session_error_detected = True
                        if end_mowing_session(state, now):
                            storage_changed = True
                            
            # Check pending confirmation 5 minutes timeout
            if state.pending_mowing_confirmation:
                if check_pending_mowing_confirmation(state, now):
                    storage_changed = True

            if self._schedule_latched_error_reset_if_needed(robot_id, now):
                storage_changed = True
            if self._schedule_late_start_kick_if_needed(robot_id, now):
                storage_changed = True
            
        if storage_changed:
            _LOGGER.debug("Storage changed during watchdog check, scheduling delayed save")
            self._storage.async_delay_save(self.get_storage_data, 10.0)
            
        # Run daily attention assessment (which also notifies callbacks)
        self.evaluate_all_daily_attention(now)

    def evaluate_all_daily_attention(self, now: datetime) -> None:
        """Evaluate daily attention states for all robots and rebuild the summary."""
        # Calculate daily observation complete flag
        local_date = get_daily_date(now)
        
        # Check if date changed to do manager-level daily rollover tracking
        if self.daily_observation_started_at != local_date:
            self.daily_observation_started_at = local_date
            self.daily_tracking_initialized = True
            
        obs_complete = self.daily_observation_complete
        
        attention_robots = []
        monitoring_names = []
        
        for robot_id, state in self.robots.items():
            # Run the rollover check on state too in case it was missed
            check_daily_rollover(state, now)
            
            # Evaluate daily attention
            from .daily_assessment import evaluate_daily_attention
            res = evaluate_daily_attention(state, now, obs_complete)
            
            # Update state properties
            state.daily_attention_required = res.required
            state.daily_attention_state = res.state
            state.daily_attention_reason_codes = res.reason_codes
            state.daily_attention_text = res.text
            state.daily_attention_evaluated_at = now.isoformat()
            
            if res.required:
                attention_robots.append((robot_id, state, res))
            elif res.state == "monitoring":
                monitoring_names.append(state.display_name)
                
        # Build summary
        from .const import ROBOTS
        attention_robots_sorted = []
        for r_id in ROBOTS:
            for item in attention_robots:
                if item[0] == r_id:
                    attention_robots_sorted.append(item)
                    break
                    
        robot_ids = [item[0] for item in attention_robots_sorted]
        robot_names = [item[1].display_name for item in attention_robots_sorted]
        
        # Event title
        if robot_names:
            event_title = "Bot " + ", ".join(robot_names)
        else:
            event_title = None
            
        # Summary text
        count = len(robot_names)
        if count == 0:
            summary_text = "Alla robotar ser normala ut."
        elif count == 1:
            summary_text = "1 robot behöver ses över."
        else:
            summary_text = f"{count} robotar behöver ses över."
            
        # Details list
        details = []
        for r_id, state, res in attention_robots_sorted:
            code = res.reason_codes[0] if res.reason_codes else ""
            if code in (
                "ACTIVE_ERROR",
                "CLEARED_BUT_UNVERIFIED",
                "FAILED_RECOVERY",
                "ROBOT_OFFLINE",
                "MOWER_DATA_STALE",
                "SESSION_LOST_OFFLINE",
                "ERROR_DURING_MOWING",
                "ERROR_AFTER_MOWING",
            ):
                severity = "critical"
            else:
                severity = "warning"
                
            details.append({
                "robot_id": r_id,
                "display_name": state.display_name,
                "severity": severity,
                "daily_attention_state": res.state,
                "reason_codes": res.reason_codes,
                "text": res.text,
            })
            
        from .daily_assessment import daily_check_started, daily_schedule_finished
        
        self.daily_attention_summary = {
            "attention_count": count,
            "robot_ids": robot_ids,
            "robot_names": robot_names,
            "event_title": event_title,
            "summary_text": summary_text,
            "details": details,
            "last_evaluated_at": now.isoformat(),
            "schedule_check_started": daily_check_started(now),
            "schedule_finished": daily_schedule_finished(now),
            "monitoring_names": monitoring_names,
            "monitoring_count": len(monitoring_names),
        }
        
        # Notify registered UI sensors
        self._notify_callbacks()

    @property
    def daily_observation_complete(self) -> bool:
        """Return True if the daily observation is complete for today."""
        now = dt_util.now()
        local_date = get_daily_date(now)
        if self.daily_observation_started_at != local_date:
            return False
        return self.daily_tracking_initialized

    @property
    def config_entry(self):
        """Get config entry of DOMAIN."""
        entries = self.hass.config_entries.async_entries(DOMAIN)
        return entries[0] if entries else None

    @property
    def calendar_enabled(self) -> bool:
        """Return True if calendar is enabled."""
        entry = self.config_entry
        if not entry:
            return False
        return bool(entry.options.get(CONF_CALENDAR_ENABLED, False))

    @property
    def calendar_entity_id(self) -> str | None:
        """Return target calendar entity ID."""
        entry = self.config_entry
        if not entry:
            return None
        val = entry.options.get(CONF_CALENDAR_ENTITY_ID)
        return str(val).strip() if val else None

    @property
    def evening_sync_time(self) -> str:
        """Return evening sync time config."""
        entry = self.config_entry
        return entry.options.get(CONF_EVENING_SYNC_TIME, DEFAULT_EVENING_SYNC_TIME) if entry else DEFAULT_EVENING_SYNC_TIME

    @property
    def morning_sync_time(self) -> str:
        """Return morning sync time config."""
        entry = self.config_entry
        return entry.options.get(CONF_MORNING_SYNC_TIME, DEFAULT_MORNING_SYNC_TIME) if entry else DEFAULT_MORNING_SYNC_TIME

    @property
    def calendar_event_start_time(self) -> str:
        """Return event start time config."""
        entry = self.config_entry
        return entry.options.get(CONF_CALENDAR_EVENT_START_TIME, DEFAULT_CALENDAR_EVENT_START_TIME) if entry else DEFAULT_CALENDAR_EVENT_START_TIME

    @property
    def calendar_event_duration_minutes(self) -> int:
        """Return event duration config in minutes."""
        entry = self.config_entry
        return int(entry.options.get(CONF_CALENDAR_EVENT_DURATION, DEFAULT_CALENDAR_EVENT_DURATION)) if entry else DEFAULT_CALENDAR_EVENT_DURATION

    def setup_calendar_timers(self) -> None:
        """Set up async_track_time_change timers for evening and morning syncs."""
        for unsub in self._unsub_calendar_timers:
            try:
                unsub()
            except Exception:
                pass
        self._unsub_calendar_timers.clear()

        if not self.calendar_enabled:
            _LOGGER.info("Calendar sync is disabled by configuration")
            return

        try:
            ev_h, ev_m = map(int, self.evening_sync_time.split(":"))
        except Exception:
            ev_h, ev_m = 20, 0

        try:
            mo_h, mo_m = map(int, self.morning_sync_time.split(":"))
        except Exception:
            mo_h, mo_m = 11, 20

        from homeassistant.helpers.event import async_track_time_change

        async def evening_timer_callback(_datetime):
            _LOGGER.info("Evening calendar sync triggered at %s", _datetime)
            await self.async_run_evening_calendar_sync(dt_util.now())

        unsub_ev = async_track_time_change(
            self.hass,
            evening_timer_callback,
            hour=ev_h,
            minute=ev_m,
            second=0
        )
        self._unsub_calendar_timers.append(unsub_ev)

        async def morning_timer_callback(_datetime):
            _LOGGER.info("Morning calendar sync triggered at %s", _datetime)
            await self.async_run_morning_calendar_sync(dt_util.now())

        unsub_mo = async_track_time_change(
            self.hass,
            morning_timer_callback,
            hour=mo_h,
            minute=mo_m,
            second=0
        )
        self._unsub_calendar_timers.append(unsub_mo)

        async def targeted_wakeup_callback(_datetime):
            if self._morning_wakeup_task is None or self._morning_wakeup_task.done():
                self._morning_wakeup_task = self.hass.async_create_task(
                    self._async_run_targeted_morning_wakeup(dt_util.now())
                )

        unsub_wakeup = async_track_time_change(
            self.hass,
            targeted_wakeup_callback,
            hour=TARGETED_WAKEUP_HOUR,
            minute=TARGETED_WAKEUP_MINUTE,
            second=0,
        )
        self._unsub_calendar_timers.append(unsub_wakeup)

        async def reconciliation_interval_callback(_datetime):
            await self._async_service_window_reconciliation_tick(dt_util.now())

        unsub_reconcile = async_track_time_interval(
            self.hass,
            reconciliation_interval_callback,
            timedelta(minutes=5),
        )
        self._unsub_calendar_timers.append(unsub_reconcile)

        _LOGGER.info(
            "Registered calendar sync timers: evening at %02d:%02d, morning at %02d:%02d, "
            "targeted wake-up at %02d:%02d, service-window reconciliation every 5 minutes",
            ev_h, ev_m, mo_h, mo_m,
            TARGETED_WAKEUP_HOUR, TARGETED_WAKEUP_MINUTE,
        )

    async def async_check_missed_syncs(self) -> None:
        """Check if any scheduled syncs were missed during downtime and execute them."""
        if not self.calendar_enabled:
            return

        from .calendar_sync import get_stockholm_timezone
        tz = get_stockholm_timezone()
        now = dt_util.now().astimezone(tz)
        current_date_str = now.date().isoformat()

        try:
            ev_h, ev_m = map(int, self.evening_sync_time.split(":"))
        except Exception:
            ev_h, ev_m = 20, 0

        try:
            mo_h, mo_m = map(int, self.morning_sync_time.split(":"))
        except Exception:
            mo_h, mo_m = 11, 20

        def get_date_part(iso_str: str | None) -> str | None:
            if not iso_str:
                return None
            return iso_str.split("T")[0]

        last_ev_date = get_date_part(self.last_evening_sync_at)
        last_mo_date = get_date_part(self.last_morning_sync_at)

        is_after_evening = (now.hour > ev_h) or (now.hour == ev_h and now.minute >= ev_m)
        if is_after_evening and last_ev_date != current_date_str:
            _LOGGER.info("Startup catch-up: Evening sync was missed today (last sync: %s). Running now...", self.last_evening_sync_at)
            await self.async_run_evening_calendar_sync(now)

        is_after_morning = (now.hour > mo_h) or (now.hour == mo_h and now.minute >= mo_m)
        is_before_cutoff = (now.hour < 12) or (now.hour == 12 and now.minute == 0)

        last_mo_date = get_date_part(self.last_morning_sync_at)

        if (
            is_after_morning
            and is_before_cutoff
            and last_mo_date != current_date_str
        ):
            _LOGGER.info(
                "Startup catch-up: Morning snapshot reconciliation was missed "
                "(last sync: %s). Running now...",
                self.last_morning_sync_at,
            )
            await self.async_run_morning_calendar_sync(now)

    async def _async_validate_calendar_entity(
        self,
        entity_id: str | None,
    ) -> str | None:
        """Validate the configured calendar and persist any failure result."""
        if not entity_id:
            result = "calendar_entity_missing"
        else:
            calendar_state = self.hass.states.get(entity_id)
            if calendar_state is None:
                result = "calendar_entity_missing"
            elif calendar_state.state == "unavailable":
                result = "calendar_entity_unavailable"
            else:
                return None

        self.last_calendar_sync_result = result
        self.last_calendar_sync_error = None
        self.last_calendar_sync_at = dt_util.now().isoformat()
        await self._storage.async_save(self.get_storage_data())
        self._notify_callbacks()
        return result

    def _parse_calendar_event_start_time(self) -> tuple[int, int]:
        """Parse configured event start time, falling back to 12:20."""
        try:
            hour, minute = map(
                int,
                self.calendar_event_start_time.split(":"),
            )
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
            return hour, minute
        except (TypeError, ValueError):
            return 12, 20

    async def _async_upsert_managed_calendar_event(
        self,
        *,
        entity_id: str,
        existing_event: dict | None,
        title: str,
        description: str,
        event_start: datetime,
        event_end: datetime,
    ) -> str:
        """Create, update, or safely replace a managed calendar event."""
        from homeassistant.components.calendar.const import (
            CalendarEntityFeature,
        )

        component = self.hass.data.get("calendar")
        entity = component.get_entity(entity_id) if component else None
        if entity is None:
            raise RuntimeError(
                f"Calendar entity {entity_id} is not available "
                "in the calendar component"
            )

        supported_features = entity.supported_features or 0
        event_payload = {
            "summary": title,
            "description": description,
            "start": event_start,
            "end": event_end,
        }

        if existing_event:
            event_uid = existing_event.get("uid")
            if not event_uid:
                raise RuntimeError(
                    "Existing managed calendar event has no UID; "
                    "it was preserved"
                )

            if supported_features & CalendarEntityFeature.UPDATE_EVENT:
                await entity.async_update_event(event_uid, event_payload)
                return "updated"

            if not (
                supported_features & CalendarEntityFeature.CREATE_EVENT
                and supported_features & CalendarEntityFeature.DELETE_EVENT
            ):
                raise RuntimeError(
                    f"Calendar entity {entity_id} supports neither direct "
                    "updates nor safe create-before-delete replacement; "
                    "the existing event was preserved"
                )

            # Create first. Delete the old event only after creation succeeds.
            await self.hass.services.async_call(
                "calendar",
                "create_event",
                {
                    "entity_id": entity_id,
                    "summary": title,
                    "description": description,
                    "start_date_time": event_start,
                    "end_date_time": event_end,
                },
                blocking=True,
            )
            await entity.async_delete_event(event_uid)
            return "replaced_safely"

        if not supported_features & CalendarEntityFeature.CREATE_EVENT:
            raise RuntimeError(
                f"Calendar entity {entity_id} does not support event creation"
            )

        await self.hass.services.async_call(
            "calendar",
            "create_event",
            {
                "entity_id": entity_id,
                "summary": title,
                "description": description,
                "start_date_time": event_start,
                "end_date_time": event_end,
            },
            blocking=True,
        )
        return "created"

    async def _async_delete_managed_event(
        self,
        entity_id: str,
        existing_event: dict | None,
    ) -> str:
        """Delete the managed event if one exists."""
        if not existing_event:
            return "no_event_needed"

        from homeassistant.components.calendar.const import (
            CalendarEntityFeature,
        )

        component = self.hass.data.get("calendar")
        entity = component.get_entity(entity_id) if component else None
        if entity is None:
            raise RuntimeError(
                f"Calendar entity {entity_id} is not available "
                "in the calendar component"
            )

        if not (
            (entity.supported_features or 0)
            & CalendarEntityFeature.DELETE_EVENT
        ):
            raise RuntimeError(
                f"Calendar entity {entity_id} does not support event deletion; "
                "the existing event was preserved"
            )

        event_uid = existing_event.get("uid")
        if not event_uid:
            raise RuntimeError(
                "Existing managed calendar event has no UID; "
                "it was preserved"
            )

        await entity.async_delete_event(event_uid)
        return "deleted"

    async def async_run_evening_calendar_sync(self, now: datetime) -> str:
        """Run evening sync and maintain one worklist for the next service day."""
        if not self.calendar_enabled:
            return "disabled"

        entity_id = self.calendar_entity_id
        validation_result = await self._async_validate_calendar_entity(entity_id)
        if validation_result is not None:
            return validation_result

        async with self._calendar_sync_lock:
            try:
                from .calendar_sync import (
                    CalendarRobotSnapshot,
                    EveningAttentionSnapshot,
                    async_fetch_managed_event,
                    build_calendar_description,
                    get_evening_problem_desc,
                    get_next_service_date,
                    get_stockholm_timezone,
                    reconcile_service_window_snapshot,
                )

                tz = get_stockholm_timezone()
                local_now = now.astimezone(tz)
                source_date_str = local_now.date().isoformat()
                target_date = get_next_service_date(
                    local_now,
                    include_current=False,
                )
                target_date_str = target_date.isoformat()

                self.evaluate_all_daily_attention(now)

                attention_robots = []
                for robot_id, state in self.robots.items():
                    if not state.daily_attention_required:
                        continue

                    severity = "warning"
                    code = (
                        state.daily_attention_reason_codes[0]
                        if state.daily_attention_reason_codes
                        else ""
                    )
                    if code in (
                        "ACTIVE_ERROR",
                        "CLEARED_BUT_UNVERIFIED",
                        "FAILED_RECOVERY",
                        "ROBOT_OFFLINE",
                        "SESSION_LOST_OFFLINE",
                        "ERROR_DURING_MOWING",
                        "ERROR_AFTER_MOWING",
                    ):
                        severity = "critical"

                    attention_robots.append(
                        CalendarRobotSnapshot(
                            robot_id=robot_id,
                            display_name=state.display_name,
                            severity=severity,
                            reason_codes=list(
                                state.daily_attention_reason_codes
                            ),
                            text=state.daily_attention_text or "",
                            captured_at=local_now.isoformat(),
                            current_status_plain=state.current_status_plain,
                            current_battery=state.current_battery,
                            online=state.online,
                            last_real_error=state.last_real_error,
                            recovery_state=str(state.recovery_state.value),
                            last_mowing_attempt_result=(
                                state.last_mowing_attempt_result
                            ),
                        )
                    )

                attention_robots, _resolved_ids = (
                    reconcile_service_window_snapshot(
                        self.calendar_snapshot,
                        target_date_str,
                        self.robots,
                        attention_robots,
                        local_now,
                        allow_active_activity_resolution=False,
                    )
                )

                snapshot = EveningAttentionSnapshot(
                    source_date=source_date_str,
                    target_calendar_date=target_date_str,
                    captured_at=local_now.isoformat(),
                    robots=attention_robots,
                )
                self.calendar_snapshot = snapshot
                self.last_evening_sync_at = local_now.isoformat()

                existing_event = await async_fetch_managed_event(
                    self.hass,
                    entity_id,
                    target_date_str,
                )

                from .const import ROBOTS

                robots_by_id = {
                    robot.robot_id: robot for robot in attention_robots
                }
                sorted_robots = [
                    robots_by_id[robot_id]
                    for robot_id in ROBOTS
                    if robot_id in robots_by_id
                ]

                start_h, start_m = self._parse_calendar_event_start_time()
                event_start = datetime.fromisoformat(
                    f"{target_date_str}T{start_h:02d}:{start_m:02d}:00"
                ).replace(tzinfo=tz)
                event_end = event_start + timedelta(
                    minutes=self.calendar_event_duration_minutes
                )

                if sorted_robots:
                    title = "Bot " + ", ".join(
                        robot.display_name for robot in sorted_robots
                    )
                    robots_data = [
                        {
                            "display_name": robot.display_name,
                            "evening_text": get_evening_problem_desc(robot),
                            "current_status": (
                                robot.current_status_plain or "saknas"
                            ),
                            "battery": robot.current_battery,
                        }
                        for robot in sorted_robots
                    ]
                    description = build_calendar_description(
                        robots_data=robots_data,
                        sync_time_str=local_now.strftime(
                            "%Y-%m-%d %H:%M"
                        ),
                        date_str=target_date_str,
                        is_morning=False,
                    )

                    result_code = (
                        await self._async_upsert_managed_calendar_event(
                            entity_id=entity_id,
                            existing_event=existing_event,
                            title=title,
                            description=description,
                            event_start=event_start,
                            event_end=event_end,
                        )
                    )

                    fetched = await async_fetch_managed_event(
                        self.hass,
                        entity_id,
                        target_date_str,
                    )
                    self.event_cache = {
                        "date": target_date_str,
                        "uid": fetched.get("uid") if fetched else None,
                        "event_id": (
                            fetched.get("uid") if fetched else None
                        ),
                        "marker": (
                            f"[AUTOMOWER_SUPERVISOR:v1:"
                            f"{target_date_str}]"
                        ),
                    }
                else:
                    result_code = await self._async_delete_managed_event(
                        entity_id,
                        existing_event,
                    )
                    self.event_cache = {}

                self.last_calendar_sync_result = result_code
                self.last_calendar_sync_error = None
                self.last_calendar_sync_at = local_now.isoformat()

                await self._storage.async_save(self.get_storage_data())
                self._notify_callbacks()
                return result_code

            except Exception as err:
                _LOGGER.error("Error during evening calendar sync: %s", err)
                self.last_calendar_sync_result = "error"
                self.last_calendar_sync_error = str(err)
                self.last_calendar_sync_at = dt_util.now().isoformat()
                await self._storage.async_save(self.get_storage_data())
                self._notify_callbacks()
                return "error"

    async def async_run_morning_calendar_sync(self, now: datetime) -> str:
        """Reconcile the service-window snapshot every morning at configured time."""
        if not self.calendar_enabled:
            return "disabled"

        async with self._calendar_sync_lock:
            try:
                from .calendar_sync import (
                    CalendarRobotSnapshot,
                    EveningAttentionSnapshot,
                    async_fetch_managed_event,
                    build_calendar_description,
                    evaluate_morning_resolution,
                    get_evening_problem_desc,
                    get_next_service_date,
                    get_stockholm_timezone,
                    is_service_day,
                    reconcile_service_window_snapshot,
                )

                tz = get_stockholm_timezone()
                local_now = now.astimezone(tz)
                current_date_str = local_now.date().isoformat()
                service_day = is_service_day(local_now.date())
                target_date = get_next_service_date(
                    local_now,
                    include_current=True,
                )
                target_date_str = target_date.isoformat()

                def current_critical_snapshot(
                    robot_id: str,
                    state: RobotState,
                ) -> CalendarRobotSnapshot | None:
                    reason = None
                    text = state.daily_attention_text or ""

                    if (
                        state.current_error_active is True
                        or state.binary_error == "on"
                        or state.recovery_state == RecoveryState.ACTIVE_ERROR
                    ):
                        reason = "ACTIVE_ERROR"
                        text = text or (
                            f'{state.display_name}: Aktivt fel '
                            f'"{state.last_real_error or "Okänt fel"}."'
                        )
                    elif (
                        state.recovery_state
                        == RecoveryState.CLEARED_BUT_UNVERIFIED
                    ):
                        reason = "CLEARED_BUT_UNVERIFIED"
                        text = text or (
                            f'{state.display_name}: Tidigare fel '
                            f'"{state.last_real_error or "Okänt fel"}" är '
                            "nollställt men inte verifierat återställt."
                        )
                    elif state.failed_recovery is True:
                        reason = "FAILED_RECOVERY"
                        text = text or (
                            f"{state.display_name}: Misslyckad återhämtning efter fel."
                        )
                    elif state.online is False:
                        reason = "ROBOT_OFFLINE"
                        text = text or f"{state.display_name}: Roboten är offline."
                    elif state.charging_stalled is True:
                        reason = "CHARGING_STALLED"
                        text = text or (
                            f"{state.display_name}: Roboten står som Charging "
                            "men batteriet minskar."
                        )

                    if reason is None:
                        return None

                    return CalendarRobotSnapshot(
                        robot_id=robot_id,
                        display_name=state.display_name,
                        severity="critical",
                        reason_codes=[reason],
                        text=text,
                        captured_at=local_now.isoformat(),
                        current_status_plain=state.current_status_plain,
                        current_battery=state.current_battery,
                        online=state.online,
                        last_real_error=state.last_real_error,
                        recovery_state=str(state.recovery_state.value),
                        last_mowing_attempt_result=(
                            state.last_mowing_attempt_result
                        ),
                    )

                current_critical = []
                for robot_id, state in self.robots.items():
                    snapshot_robot = current_critical_snapshot(robot_id, state)
                    if snapshot_robot is not None:
                        current_critical.append(snapshot_robot)

                reconciled_robots, resolved_ids = (
                    reconcile_service_window_snapshot(
                        self.calendar_snapshot,
                        target_date_str,
                        self.robots,
                        current_critical,
                        local_now,
                        allow_active_activity_resolution=service_day,
                    )
                )

                self.calendar_snapshot = EveningAttentionSnapshot(
                    source_date=current_date_str,
                    target_calendar_date=target_date_str,
                    captured_at=local_now.isoformat(),
                    robots=reconciled_robots,
                )
                self.morning_reconciled_at = local_now.isoformat()
                self.morning_remaining_robot_ids = [
                    robot.robot_id for robot in reconciled_robots
                ]
                self.morning_resolved_robot_ids = list(
                    dict.fromkeys(resolved_ids)
                )
                self.last_morning_sync_at = local_now.isoformat()

                if not service_day:
                    self.last_calendar_sync_result = (
                        "snapshot_reconciled_non_service_day"
                    )
                    self.last_calendar_sync_error = None
                    self.last_calendar_sync_at = local_now.isoformat()
                    await self._storage.async_save(self.get_storage_data())
                    self._notify_callbacks()
                    return "snapshot_reconciled_non_service_day"

                entity_id = self.calendar_entity_id
                validation_result = await self._async_validate_calendar_entity(
                    entity_id
                )
                if validation_result is not None:
                    return validation_result

                remaining_robots_data = []
                remaining_snapshot_robots = []
                final_resolved_ids = list(resolved_ids)

                for snapshot_robot in reconciled_robots:
                    current_state = self.robots[snapshot_robot.robot_id]
                    resolution = evaluate_morning_resolution(
                        snapshot_robot,
                        current_state,
                        local_now,
                    )
                    if resolution.keep:
                        remaining_snapshot_robots.append(snapshot_robot)
                        remaining_robots_data.append(
                            {
                                "robot_id": snapshot_robot.robot_id,
                                "display_name": current_state.display_name,
                                "evening_text": get_evening_problem_desc(
                                    snapshot_robot
                                ),
                                "current_status": (
                                    current_state.current_status_plain
                                    or current_state.current_status
                                    or "saknas"
                                ),
                                "battery": current_state.current_battery,
                                "recovery_state": (
                                    str(current_state.recovery_state.value)
                                    if current_state.recovery_state
                                    != RecoveryState.NONE
                                    else "none"
                                ),
                                "morning_status_text": resolution.text,
                            }
                        )
                    else:
                        final_resolved_ids.append(snapshot_robot.robot_id)

                from .const import ROBOTS

                remaining_by_id = {
                    item["robot_id"]: item
                    for item in remaining_robots_data
                }
                sorted_remaining_data = [
                    remaining_by_id[robot_id]
                    for robot_id in ROBOTS
                    if robot_id in remaining_by_id
                ]
                remaining_snapshot_by_id = {
                    robot.robot_id: robot
                    for robot in remaining_snapshot_robots
                }
                sorted_remaining_snapshots = [
                    remaining_snapshot_by_id[robot_id]
                    for robot_id in ROBOTS
                    if robot_id in remaining_snapshot_by_id
                ]

                self.calendar_snapshot = EveningAttentionSnapshot(
                    source_date=current_date_str,
                    target_calendar_date=target_date_str,
                    captured_at=local_now.isoformat(),
                    robots=sorted_remaining_snapshots,
                )
                self.morning_remaining_robot_ids = [
                    robot.robot_id for robot in sorted_remaining_snapshots
                ]
                self.morning_resolved_robot_ids = list(
                    dict.fromkeys(final_resolved_ids)
                )

                existing_event = await async_fetch_managed_event(
                    self.hass,
                    entity_id,
                    current_date_str,
                )

                start_h, start_m = self._parse_calendar_event_start_time()
                event_start = datetime.fromisoformat(
                    f"{current_date_str}T{start_h:02d}:{start_m:02d}:00"
                ).replace(tzinfo=tz)
                event_end = event_start + timedelta(
                    minutes=self.calendar_event_duration_minutes
                )

                if sorted_remaining_data:
                    title = "Bot " + ", ".join(
                        item["display_name"]
                        for item in sorted_remaining_data
                    )
                    description = build_calendar_description(
                        robots_data=sorted_remaining_data,
                        sync_time_str=local_now.strftime(
                            "%Y-%m-%d %H:%M"
                        ),
                        date_str=current_date_str,
                        is_morning=True,
                    )
                    result_code = (
                        await self._async_upsert_managed_calendar_event(
                            entity_id=entity_id,
                            existing_event=existing_event,
                            title=title,
                            description=description,
                            event_start=event_start,
                            event_end=event_end,
                        )
                    )

                    fetched = await async_fetch_managed_event(
                        self.hass,
                        entity_id,
                        current_date_str,
                    )
                    self.event_cache = {
                        "date": current_date_str,
                        "uid": fetched.get("uid") if fetched else None,
                        "event_id": (
                            fetched.get("uid") if fetched else None
                        ),
                        "marker": (
                            f"[AUTOMOWER_SUPERVISOR:v1:"
                            f"{current_date_str}]"
                        ),
                    }
                else:
                    result_code = await self._async_delete_managed_event(
                        entity_id,
                        existing_event,
                    )
                    self.event_cache = {}

                self.last_calendar_sync_result = result_code
                self.last_calendar_sync_error = None
                self.last_calendar_sync_at = local_now.isoformat()

                await self._storage.async_save(self.get_storage_data())
                self._notify_callbacks()
                return result_code

            except Exception as err:
                _LOGGER.error("Error during morning calendar sync: %s", err)
                self.last_calendar_sync_result = "error"
                self.last_calendar_sync_error = str(err)
                self.last_calendar_sync_at = dt_util.now().isoformat()
                await self._storage.async_save(self.get_storage_data())
                self._notify_callbacks()
                return "error"

    def register_services(self) -> None:
        """Register services for calendar synchronization."""
        
        async def sync_calendar_service(call):
            mode = call.data.get("mode", "auto")
            now = dt_util.now()
            from .calendar_sync import get_stockholm_timezone
            tz = get_stockholm_timezone()
            local_now = now.astimezone(tz)
            
            if mode == "evening":
                await self.async_run_evening_calendar_sync(now)
            elif mode == "morning":
                await self.async_run_morning_calendar_sync(now)
            else: # auto
                if local_now.hour < 12:
                    await self.async_run_morning_calendar_sync(now)
                else:
                    await self.async_run_evening_calendar_sync(now)

        self.hass.services.async_register(
            DOMAIN,
            "sync_calendar",
            sync_calendar_service,
        )

        async def delete_managed_calendar_event_service(call):
            """Delete all managed Automower events in the relevant service window."""
            entity_id = self.calendar_entity_id
            if not entity_id:
                return

            from .calendar_sync import (
                async_fetch_managed_event,
                get_stockholm_timezone,
            )

            tz = get_stockholm_timezone()
            local_now = dt_util.now().astimezone(tz)

            component = self.hass.data.get("calendar")
            entity = component.get_entity(entity_id) if component else None
            if entity is None:
                raise RuntimeError(
                    f"Calendar entity {entity_id} is not available "
                    "in the calendar component"
                )

            candidate_dates: set[str] = set()

            cached_date = self.event_cache.get("date")
            if cached_date:
                candidate_dates.add(cached_date)

            if self.calendar_snapshot is not None:
                snapshot_date = self.calendar_snapshot.target_calendar_date
                if snapshot_date:
                    candidate_dates.add(snapshot_date)

            for offset in range(-1, 8):
                candidate_dates.add(
                    (
                        local_now.date() + timedelta(days=offset)
                    ).isoformat()
                )

            deleted_uids: set[str] = set()

            for date_str in sorted(candidate_dates):
                existing_event = await async_fetch_managed_event(
                    self.hass,
                    entity_id,
                    date_str,
                )
                if not existing_event:
                    continue

                event_uid = existing_event.get("uid")
                if not event_uid or event_uid in deleted_uids:
                    continue

                await entity.async_delete_event(event_uid)
                deleted_uids.add(event_uid)

            self.event_cache = {}
            self.calendar_snapshot = None
            await self._storage.async_save(self.get_storage_data())
            self._notify_callbacks()

        self.hass.services.async_register(
            DOMAIN,
            "delete_managed_calendar_event",
            delete_managed_calendar_event_service,
        )
