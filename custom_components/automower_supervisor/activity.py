"""Activity and mowing session tracking for the Automower Supervisor integration."""

from __future__ import annotations
from datetime import datetime
import logging
from typing import Any

import homeassistant.util.dt as dt_util

from .models import RobotState, RecoveryState
from .schedule import get_daily_date

_LOGGER = logging.getLogger(__name__)


def safe_float(val: Any) -> float | None:
    """Safely convert value to float, handling commas, empty strings, None, and unknown/unavailable."""
    if val is None:
        return None
    val_str = str(val).strip().replace(",", ".")
    if val_str.lower() in ("unknown", "unavailable", ""):
        return None
    try:
        return float(val_str)
    except (ValueError, TypeError):
        return None


def safe_int(val: Any) -> int | None:
    """Safely convert value to integer."""
    f = safe_float(val)
    return int(f) if f is not None else None


def update_accumulated_mowing_time(state: RobotState, now: datetime) -> None:
    """Update accumulated mowing seconds and session elapsed seconds up to now."""
    if state.mowing_session_active and state.current_mowing_segment_started_at:
        try:
            seg_start = datetime.fromisoformat(state.current_mowing_segment_started_at)
            now_utc = dt_util.as_utc(now)
            seg_start_utc = dt_util.as_utc(seg_start)
            diff = (now_utc - seg_start_utc).total_seconds()
            if diff > 0:
                state.accumulated_mowing_seconds += int(diff)
                state.current_mowing_segment_started_at = now_utc.isoformat()
        except Exception as err:
            _LOGGER.error("Error updating accumulated mowing time: %s", err)
            
    if state.mowing_session_active and state.session_started_at:
        try:
            start_time = datetime.fromisoformat(state.session_started_at)
            now_utc = dt_util.as_utc(now)
            start_utc = dt_util.as_utc(start_time)
            state.session_elapsed_seconds = int((now_utc - start_utc).total_seconds())
        except Exception as err:
            _LOGGER.error("Error updating session elapsed seconds: %s", err)


def update_session_latest_values(state: RobotState) -> None:
    """Update active session latest values from current robot state."""
    if state.mowing_session_active:
        if state.current_battery is not None:
            state.session_latest_battery = state.current_battery
            if state.session_start_battery is None:
                state.session_start_battery = state.current_battery
                
        if state.last_distance_value is not None:
            state.session_latest_distance = state.last_distance_value
            if state.session_start_distance is None:
                state.session_start_distance = state.last_distance_value
                
        if state.last_runtime_hours_value is not None:
            state.session_latest_runtime_hours = state.last_runtime_hours_value
            if state.session_start_runtime_hours is None:
                state.session_start_runtime_hours = state.last_runtime_hours_value


def end_mowing_session(state: RobotState, now: datetime, result_override: str | None = None) -> bool:
    """End the active mowing session. Returns True if storage needs saving."""
    if not state.mowing_session_active:
        return False
        
    # Update latest values and segment before closing
    update_accumulated_mowing_time(state, now)
    update_session_latest_values(state)
    
    # Classify session result
    if state.session_error_detected or state.session_binary_error_detected:
        result = "failed_error_during_mowing"
    elif result_override:
        result = result_override
    else:
        mowing_minutes = state.accumulated_mowing_seconds / 60.0
        if mowing_minutes < 3.0:
            result = "short_attempt"
        elif mowing_minutes < 10.0:
            result = "uncertain_attempt"
        else:
            result = "confirmation_candidate"
            
    # Save last attempt data
    state.last_mowing_attempt_at = state.session_started_at
    state.last_mowing_attempt_duration_seconds = state.accumulated_mowing_seconds
    state.last_mowing_session_elapsed_seconds = state.session_elapsed_seconds
    state.last_mowing_attempt_result = result
    state.last_mowing_ended_at = dt_util.as_utc(now).isoformat()
    
    storage_changed = True
    
    # Candidate evaluation
    if result == "confirmation_candidate":
        # Check supporting signals:
        # Distance delta >= 1.0
        has_distance_signal = False
        if (state.session_start_distance is not None and 
            state.session_latest_distance is not None):
            delta = state.session_latest_distance - state.session_start_distance
            if delta >= 1.0:
                has_distance_signal = True
                
        # Runtime delta >= 0.01
        has_runtime_signal = False
        if (state.session_start_runtime_hours is not None and 
            state.session_latest_runtime_hours is not None):
            delta = state.session_latest_runtime_hours - state.session_start_runtime_hours
            if delta >= 0.01:
                has_runtime_signal = True
                
        # Battery drop >= 2
        has_battery_signal = False
        if (state.session_start_battery is not None and 
            state.session_latest_battery is not None):
            delta = state.session_start_battery - state.session_latest_battery
            if delta >= 2:
                has_battery_signal = True
                
        if has_distance_signal or has_runtime_signal or has_battery_signal:
            state.pending_mowing_confirmation = True
        else:
            state.last_mowing_attempt_result = "insufficient_supporting_data"
    elif result == "failed_error_during_mowing":
        if state.recovery_state in (RecoveryState.CLEARED_BUT_UNVERIFIED, RecoveryState.ACTIVE_ERROR):
            state.failed_recovery = True
            
    # Clear active session fields
    state.mowing_session_active = False
    state.session_started_at = None
    state.session_started_source = None
    state.session_elapsed_seconds = 0
    state.accumulated_mowing_seconds = 0
    state.current_mowing_segment_started_at = None
    state.interruption_started_at = None
    state.interruption_status = None
    state.pending_session_end = False
    state.session_start_battery = None
    state.session_start_distance = None
    state.session_start_runtime_hours = None
    state.session_latest_battery = None
    state.session_latest_distance = None
    state.session_latest_runtime_hours = None
    state.session_error_detected = False
    state.session_binary_error_detected = False
    
    return storage_changed


def check_pending_mowing_confirmation(state: RobotState, now: datetime) -> bool:
    """Check if the 5-minute grace period has passed for a pending mowing confirmation. Returns True if storage changed."""
    if not state.pending_mowing_confirmation or not state.last_mowing_ended_at:
        return False
        
    try:
        ended_at = datetime.fromisoformat(state.last_mowing_ended_at)
        now_utc = dt_util.as_utc(now)
        ended_at_utc = dt_util.as_utc(ended_at)
        elapsed = (now_utc - ended_at_utc).total_seconds()
        
        if elapsed >= 300:  # 5 minutes
            state.pending_mowing_confirmation = False
            state.last_mowing_attempt_result = "confirmed_mowing"
            state.last_confirmed_mowing_at = state.last_mowing_ended_at
            state.last_confirmed_mowing_duration_seconds = state.last_mowing_attempt_duration_seconds
            state.confirmed_mowing_today = True
            
            # Verify recovery if cleared but unverified and error category is cutting, other, or none
            if state.recovery_state == RecoveryState.CLEARED_BUT_UNVERIFIED:
                if state.last_real_error_category in ("cutting", "other", "none"):
                    state.recovery_state = RecoveryState.RECOVERED
                    state.failed_recovery = False
                    state.recovery_verified_at = now_utc.isoformat()
            return True
    except Exception as err:
        _LOGGER.error("Error checking pending mowing confirmation: %s", err)
    return False


def handle_status_change(state: RobotState, new_status: str | None, now: datetime) -> bool:
    """Handle robot status change and run mowing session state machine. Returns True if storage changed."""
    now_utc = dt_util.as_utc(now)
    if not new_status:
        if state.mowing_session_active and not state.pending_session_end:
            update_accumulated_mowing_time(state, now_utc)
            state.current_mowing_segment_started_at = None
            state.interruption_started_at = now_utc.isoformat()
            state.interruption_status = "unknown"
            state.pending_session_end = True
            return True
        return False
        
    norm_status = new_status.strip().lower()
    
    terminating_statuses = {
        "error", "fault", "charging", "sleeping", "parked", 
        "way home", "searching for charging station", "stopped", "off"
    }
    
    if norm_status in terminating_statuses:
        if state.mowing_session_active:
            if norm_status in ("error", "fault"):
                state.session_error_detected = True
            return end_mowing_session(state, now_utc)
        return False
        
    if norm_status == "mowing":
        storage_changed = False
        if not state.mowing_session_active:
            state.mowing_session_active = True
            state.session_started_at = now_utc.isoformat()
            state.session_started_source = "state_event"
            state.current_mowing_segment_started_at = now_utc.isoformat()
            state.accumulated_mowing_seconds = 0
            state.session_elapsed_seconds = 0
            
            # Populate initial supporting sensor values if available
            state.session_start_battery = state.current_battery
            state.session_start_distance = state.last_distance_value
            state.session_start_runtime_hours = state.last_runtime_hours_value
            
            state.session_latest_battery = state.current_battery
            state.session_latest_distance = state.last_distance_value
            state.session_latest_runtime_hours = state.last_runtime_hours_value
            
            state.session_error_detected = False
            state.session_binary_error_detected = False
            state.pending_session_end = False
            state.pending_mowing_confirmation = False
            
            state.mowing_attempted_today = True
            state.last_mowing_attempt_at = state.session_started_at
            storage_changed = True
        else:
            if state.pending_session_end:
                state.current_mowing_segment_started_at = now_utc.isoformat()
                state.interruption_started_at = None
                state.interruption_status = None
                state.pending_session_end = False
                storage_changed = True
        return storage_changed
        
    if norm_status in ("searching", "detecting status"):
        if state.mowing_session_active and not state.pending_session_end:
            update_accumulated_mowing_time(state, now_utc)
            state.current_mowing_segment_started_at = None
            state.interruption_started_at = now_utc.isoformat()
            state.interruption_status = new_status
            state.pending_session_end = True
            return True
        return False
        
    # Fallback: treat any other status as terminating
    if state.mowing_session_active:
        return end_mowing_session(state, now_utc)
        
    return False


def check_daily_rollover(state: RobotState, now: datetime) -> bool:
    """Perform daily rollover. Returns True if storage changed."""
    current_date = get_daily_date(now)
    if state.daily_date != current_date:
        state.daily_date = current_date
        state.confirmed_mowing_today = False
        state.mowing_attempted_today = False
        return True
    return False
