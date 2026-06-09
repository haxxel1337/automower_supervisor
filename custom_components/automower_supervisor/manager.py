"""Central manager for the Automower Supervisor integration."""

from __future__ import annotations

import logging
from typing import Any, Callable

from homeassistant.core import HomeAssistant, Event
from homeassistant.helpers.event import async_track_state_change_event
import homeassistant.util.dt as dt_util

from .const import ROBOTS, ENTITY_PATTERNS, NO_ACTIVE_ERROR_VALUES
from .models import RobotState, RecoveryState
from .storage import AutomowerSupervisorStorage

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


def safe_int(val: Any) -> int | None:
    """Safely convert value to integer."""
    try:
        return int(float(str(val)))
    except (ValueError, TypeError):
        return None


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
        self.sync_initial_states()
        
        # Register listeners
        self.setup_listeners()

    async def _async_load_storage(self) -> None:
        """Load persistent storage and apply it to the robot states."""
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
            }
        return data

    def sync_initial_states(self) -> None:
        """Sync initial states of entities from Home Assistant."""
        current_time_iso = dt_util.now().isoformat()
        
        for robot_id, state in self.robots.items():
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
            self._update_robot_error_state(robot_id, current_time_iso)

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
        
        # Update lists and state values
        if new_state is None:
            _update_entity_state_lists(state, entity_id, "missing")
            self._update_state_field(state, key, None)
        elif new_state.state == "unavailable":
            _update_entity_state_lists(state, entity_id, "unavailable")
            self._update_state_field(state, key, None)
        elif new_state.state == "unknown":
            _update_entity_state_lists(state, entity_id, "unknown")
            self._update_state_field(state, key, None)
        else:
            _update_entity_state_lists(state, entity_id, None)
            self._update_state_field(state, key, new_state.state)
            
        # Re-evaluate logic for errors
        storage_changed = self._update_robot_error_state(robot_id, current_time_iso)
        
        if storage_changed:
            _LOGGER.debug("Error state changed for %s, saving to storage", robot_id)
            self._storage.async_delay_save(self.get_storage_data, 10.0)
            
        # Notify registered UI sensors
        self._notify_callbacks()

    def _update_state_field(self, state: RobotState, key: str, value: str | None) -> None:
        """Update the real-time field based on the entity key."""
        if key == "status":
            state.current_status = value
        elif key == "status_plain":
            state.current_status_plain = value
        elif key == "battery":
            state.current_battery = safe_int(value)
        elif key == "error_message":
            state.current_error_message = value
        elif key == "error_binary":
            state.binary_error = value

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
                    changed = True
        else:
            # No active error reported by sensors
            if state.recovery_state == RecoveryState.ACTIVE_ERROR:
                state.current_error_active = False
                state.recovery_state = RecoveryState.CLEARED_BUT_UNVERIFIED
                state.error_cleared_at = current_time_iso
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
            
        # Clear callbacks
        self._callbacks.clear()
            
        # Write storage synchronously/immediately before unload completes
        await self._storage.async_save(self.get_storage_data())
