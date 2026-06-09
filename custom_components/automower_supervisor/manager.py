from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any, Callable

from homeassistant.core import HomeAssistant, Event
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
import homeassistant.util.dt as dt_util

from .const import ROBOTS, ENTITY_PATTERNS, NO_ACTIVE_ERROR_VALUES
from .models import RobotState, RecoveryState
from .storage import AutomowerSupervisorStorage
from .error_classifier import classify_error
from .schedule import get_daily_date
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
        await self._async_load_storage()
        
        # Initial scan of current state machine states
        storage_changed = self.sync_initial_states(is_startup=True)
        
        # Set watchdog checked time and calculate metrics directly
        now = dt_util.now()
        self.watchdog_checked_at = now.isoformat()
        for robot_id in self.robots:
            self._update_watchdog_for_robot(robot_id, now)
            
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

    async def _async_load_storage(self) -> None:
        """Load persistent storage and apply it to the robot states."""
        # Initialize daily_date for all robots first to prevent unwanted first-run save calls
        now = dt_util.now()
        current_date = get_daily_date(now)
        for state in self.robots.values():
            state.daily_date = current_date

        stored_data = await self._storage.async_load()
        if not stored_data:
            _LOGGER.debug("No persistent storage data found")
            return
            
        _LOGGER.debug("Loading persistent storage data: %s", stored_data)
        for robot_id, data in stored_data.items():
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
            state.last_real_error_category = data.get("last_real_error_category", "none")
            
            state.pending_mowing_confirmation = bool(data.get("pending_mowing_confirmation", False))
            state.pending_confirmation_ended_at = data.get("pending_confirmation_ended_at")
            state.pending_confirmation_mowing_seconds = int(data.get("pending_confirmation_mowing_seconds", 0))
            state.pending_confirmation_session_elapsed_seconds = int(data.get("pending_confirmation_session_elapsed_seconds", 0))
            state.pending_confirmation_distance_activity = bool(data.get("pending_confirmation_distance_activity", False))
            state.pending_confirmation_runtime_activity = bool(data.get("pending_confirmation_runtime_activity", False))
            state.pending_confirmation_battery_activity = bool(data.get("pending_confirmation_battery_activity", False))
            
            state.recovery_distance_baseline = data.get("recovery_distance_baseline")
            state.recovery_accumulated_positive_distance = float(data.get("recovery_accumulated_positive_distance", 0.0))
            state.recovery_previous_distance = data.get("recovery_previous_distance")
            
            if "daily_date" in data and data["daily_date"] is not None:
                state.daily_date = data["daily_date"]

    def get_storage_data(self) -> dict[str, dict[str, Any]]:
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
                "pending_mowing_confirmation": state.pending_mowing_confirmation,
                "pending_confirmation_ended_at": state.pending_confirmation_ended_at,
                "pending_confirmation_mowing_seconds": state.pending_confirmation_mowing_seconds,
                "pending_confirmation_session_elapsed_seconds": state.pending_confirmation_session_elapsed_seconds,
                "pending_confirmation_distance_activity": state.pending_confirmation_distance_activity,
                "pending_confirmation_runtime_activity": state.pending_confirmation_runtime_activity,
                "pending_confirmation_battery_activity": state.pending_confirmation_battery_activity,
                "recovery_distance_baseline": state.recovery_distance_baseline,
                "recovery_accumulated_positive_distance": state.recovery_accumulated_positive_distance,
                "recovery_previous_distance": state.recovery_previous_distance,
                "daily_date": state.daily_date,
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
            
        # Re-evaluate logic for errors
        if self._update_robot_error_state(robot_id, current_time_iso):
            storage_changed = True
            
        if storage_changed:
            _LOGGER.debug("Data changed for %s, saving/scheduling save to storage", robot_id)
            self._storage.async_delay_save(self.get_storage_data, 10.0)
            
        # Notify registered UI sensors
        self._notify_callbacks()

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

            # If pending mowing confirmation, cancel it and mark failed_recovery = True
            if state.pending_mowing_confirmation:
                state.pending_mowing_confirmation = False
                state.last_mowing_attempt_result = "failed_error_after_mowing"
                state.failed_recovery = True
                state.pending_confirmation_ended_at = None
                state.pending_confirmation_mowing_seconds = 0
                state.pending_confirmation_session_elapsed_seconds = 0
                state.pending_confirmation_distance_activity = False
                state.pending_confirmation_runtime_activity = False
                state.pending_confirmation_battery_activity = False
                changed = True
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
            
        if storage_changed:
            _LOGGER.debug("Storage changed during watchdog check, scheduling delayed save")
            self._storage.async_delay_save(self.get_storage_data, 10.0)
            
        # Notify callbacks
        self._notify_callbacks()
