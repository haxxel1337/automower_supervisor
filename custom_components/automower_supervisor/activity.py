"""Activity and mowing session tracking for the Automower Supervisor integration."""

from __future__ import annotations
from datetime import datetime
import logging
from typing import Any

import homeassistant.util.dt as dt_util

from .models import RobotState, RecoveryState
from .schedule import get_daily_date
from .const import (
    MOWING_SHORT_MAX_MINUTES,
    RECOVERY_CONFIRM_MIN_MINUTES,
    MOWING_CONFIRM_MIN_MINUTES,
    ERROR_GRACE_PERIOD_MINUTES,
    DISTANCE_MIN_DELTA_METERS,
    RUNTIME_MIN_DELTA_HOURS,
    BATTERY_MIN_DROP_PERCENT,
)

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
    
    now_utc = dt_util.as_utc(now)
    
    # Calculate supporting signals first
    has_distance_signal = (
        state.session_accumulated_positive_distance >= DISTANCE_MIN_DELTA_METERS
        or state.session_distance_activity_detected
    )
    
    has_runtime_signal = False
    if (state.session_start_runtime_hours is not None and 
        state.session_latest_runtime_hours is not None):
        delta = state.session_latest_runtime_hours - state.session_start_runtime_hours
        if delta >= RUNTIME_MIN_DELTA_HOURS:
            has_runtime_signal = True
            
    has_battery_signal = False
    if (state.session_start_battery is not None and 
        state.session_latest_battery is not None):
        delta = state.session_start_battery - state.session_latest_battery
        if delta >= BATTERY_MIN_DROP_PERCENT:
            has_battery_signal = True
            
    has_supporting_activity = has_distance_signal or has_runtime_signal or has_battery_signal

    # Classify session result
    if state.session_error_detected or state.session_binary_error_detected:
        result = "failed_error_during_mowing"
    elif result_override:
        result = result_override
    else:
        mowing_minutes = state.accumulated_mowing_seconds / 60.0
        if mowing_minutes < MOWING_SHORT_MAX_MINUTES:
            result = "short_attempt"
        elif mowing_minutes < RECOVERY_CONFIRM_MIN_MINUTES:
            result = "uncertain_attempt"
        elif mowing_minutes < MOWING_CONFIRM_MIN_MINUTES:
            # 5 to under 10 minutes
            if state.recovery_state == RecoveryState.CLEARED_BUT_UNVERIFIED and has_supporting_activity:
                result = "recovery_confirmation_pending"
            else:
                if has_supporting_activity:
                    result = "uncertain_attempt"
                else:
                    result = "insufficient_supporting_data"
        else:
            # 10 minutes or more
            if has_supporting_activity:
                result = "confirmation_pending"
            else:
                result = "insufficient_supporting_data"
            
    # Save last attempt data
    state.last_mowing_attempt_at = state.session_started_at
    state.last_mowing_attempt_duration_seconds = state.accumulated_mowing_seconds
    state.last_mowing_session_elapsed_seconds = state.session_elapsed_seconds
    state.last_mowing_ended_at = now_utc.isoformat()
    
    storage_changed = True
    
    if result in ("recovery_confirmation_pending", "confirmation_pending"):
        state.pending_mowing_confirmation = True
        state.pending_confirmation_ended_at = now_utc.isoformat()
        state.pending_confirmation_mowing_seconds = state.accumulated_mowing_seconds
        state.pending_confirmation_session_elapsed_seconds = state.session_elapsed_seconds
        state.pending_confirmation_distance_activity = has_distance_signal
        state.pending_confirmation_runtime_activity = has_runtime_signal
        state.pending_confirmation_battery_activity = has_battery_signal
        
        if result == "recovery_confirmation_pending":
            state.pending_confirmation_type = "recovery_only"
            state.last_mowing_attempt_result = "recovery_confirmation_pending"
        else:
            state.pending_confirmation_type = "full_mowing"
            state.last_mowing_attempt_result = "confirmation_pending"
    else:
        state.last_mowing_attempt_result = result
        if result == "failed_error_during_mowing":
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
    
    state.session_previous_distance = None
    state.session_accumulated_positive_distance = 0.0
    state.session_distance_activity_detected = False
    state.distance_reset_count = 0
    
    return storage_changed


def clear_pending_confirmation_fields(state: RobotState) -> None:
    """Clear all pending confirmation fields on the RobotState."""
    state.pending_mowing_confirmation = False
    state.pending_confirmation_ended_at = None
    state.pending_confirmation_mowing_seconds = 0
    state.pending_confirmation_session_elapsed_seconds = 0
    state.pending_confirmation_distance_activity = False
    state.pending_confirmation_runtime_activity = False
    state.pending_confirmation_battery_activity = False
    state.pending_confirmation_type = None


def get_pending_confirmation_age_seconds(state: RobotState, now: datetime) -> float | None:
    """Get the age of the pending confirmation in seconds, or None if invalid/corrupt state."""
    if not state.pending_mowing_confirmation or not state.pending_confirmation_ended_at:
        return None
    try:
        ended_at = datetime.fromisoformat(state.pending_confirmation_ended_at)
        now_utc = dt_util.as_utc(now)
        ended_at_utc = dt_util.as_utc(ended_at)
        return (now_utc - ended_at_utc).total_seconds()
    except Exception as err:
        _LOGGER.warning(
            "Error parsing pending_confirmation_ended_at '%s' for robot %s: %s",
            state.pending_confirmation_ended_at,
            state.robot_id,
            err,
        )
        return None


def confirm_pending_mowing(state: RobotState, now: datetime) -> bool:
    """Finalize and confirm the pending mowing session. Returns True if storage changed."""
    if not state.pending_mowing_confirmation or not state.pending_confirmation_ended_at:
        return False
        
    now_utc = dt_util.as_utc(now)
    conf_type = state.pending_confirmation_type or "full_mowing"
    
    if conf_type == "full_mowing":
        state.last_mowing_attempt_result = "confirmed_mowing"
        state.last_confirmed_mowing_at = state.pending_confirmation_ended_at
        state.last_confirmed_mowing_duration_seconds = state.pending_confirmation_mowing_seconds
        state.confirmed_mowing_today = True
        
        # Verify recovery if cleared but unverified and error category is cutting, other, or none
        if state.recovery_state == RecoveryState.CLEARED_BUT_UNVERIFIED:
            if state.last_real_error_category in ("cutting", "other", "none"):
                state.recovery_state = RecoveryState.RECOVERED
                state.failed_recovery = False
                state.recovery_verified_at = now_utc.isoformat()
    else:  # recovery_only
        state.last_mowing_attempt_result = "recovery_verified_session"
        if state.recovery_state == RecoveryState.CLEARED_BUT_UNVERIFIED:
            if state.last_real_error_category in ("cutting", "other", "none"):
                state.recovery_state = RecoveryState.RECOVERED
                state.failed_recovery = False
                state.recovery_verified_at = now_utc.isoformat()
                
    clear_pending_confirmation_fields(state)
    return True


def fail_pending_mowing_after_error(state: RobotState) -> bool:
    """Fail the pending mowing session due to an error during grace period. Returns True if storage changed."""
    if not state.pending_mowing_confirmation:
        return False
    state.last_mowing_attempt_result = "failed_error_after_mowing"
    state.failed_recovery = True
    clear_pending_confirmation_fields(state)
    return True


def check_pending_mowing_confirmation(state: RobotState, now: datetime) -> bool:
    """Check if the 5-minute grace period has passed for a pending mowing confirmation. Returns True if storage changed."""
    if not state.pending_mowing_confirmation:
        return False
        
    if not state.pending_confirmation_ended_at:
        _LOGGER.warning(
            "Robot %s has pending_mowing_confirmation but pending_confirmation_ended_at is missing. Clearing corrupt state.",
            state.robot_id,
        )
        clear_pending_confirmation_fields(state)
        return True
        
    age = get_pending_confirmation_age_seconds(state, now)
    if age is None:
        # Corrupt date, clear pending state
        clear_pending_confirmation_fields(state)
        return True
        
    if age >= ERROR_GRACE_PERIOD_MINUTES * 60:
        return confirm_pending_mowing(state, now)
        
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
    
    TERMINATING_STATUSES = {
        "error", "fault", "charging", "sleeping", "parked", 
        "way home", "searching for charging station", "stopped", "off"
    }
    
    TEMPORARY_STATUSES = {
        "searching", "detecting status"
    }
    
    if norm_status in TERMINATING_STATUSES:
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
            
            state.session_previous_distance = state.last_distance_value
            state.session_accumulated_positive_distance = 0.0
            state.session_distance_activity_detected = False
            state.distance_reset_count = 0
            
            state.mowing_attempted_today = True
            storage_changed = True
        else:
            if state.pending_session_end:
                state.current_mowing_segment_started_at = now_utc.isoformat()
                state.interruption_started_at = None
                state.interruption_status = None
                state.pending_session_end = False
                storage_changed = True
        return storage_changed
        
    display_status = new_status
    if state.current_status and state.current_status.strip().lower() == norm_status:
        display_status = state.current_status

    if norm_status in TEMPORARY_STATUSES:
        if state.mowing_session_active and not state.pending_session_end:
            update_accumulated_mowing_time(state, now_utc)
            state.current_mowing_segment_started_at = None
            state.interruption_started_at = now_utc.isoformat()
            state.interruption_status = display_status
            state.pending_session_end = True
            return True
        return False
        
    # Fallback for other/unknown statuses: keep session open, pause segment if not already paused
    if state.mowing_session_active:
        if not state.pending_session_end:
            update_accumulated_mowing_time(state, now_utc)
            state.current_mowing_segment_started_at = None
            state.interruption_started_at = now_utc.isoformat()
            state.interruption_status = display_status
            state.pending_session_end = True
            return True
    return False


def update_robot_distance(state: RobotState, val_float: float | None) -> bool:
    """Update robot distance metrics, tracking accumulated positive distance and handling resets. Returns True if storage changed."""
    if val_float is None:
        return False
        
    storage_changed = False
    
    # 1. Active mowing session tracking
    if state.mowing_session_active:
        state.session_latest_distance = val_float
        if state.session_start_distance is None:
            state.session_start_distance = val_float
            
        if state.session_previous_distance is not None:
            delta = val_float - state.session_previous_distance
            if delta > 0:
                state.session_accumulated_positive_distance += delta
                if state.session_accumulated_positive_distance >= DISTANCE_MIN_DELTA_METERS:
                    state.session_distance_activity_detected = True
            elif val_float < state.session_previous_distance:
                # Distance reset detected!
                state.distance_reset_count += 1
                
        state.session_previous_distance = val_float
        
    # 2. Movement recovery tracking
    if state.recovery_state == RecoveryState.CLEARED_BUT_UNVERIFIED:
        if state.recovery_previous_distance is not None:
            delta = val_float - state.recovery_previous_distance
            if delta > 0:
                state.recovery_accumulated_positive_distance += delta
                if state.recovery_accumulated_positive_distance >= DISTANCE_MIN_DELTA_METERS and state.last_real_error_category == "movement":
                    state.recovery_state = RecoveryState.RECOVERED
                    state.failed_recovery = False
                    state.recovery_verified_at = dt_util.as_utc(dt_util.now()).isoformat()
                    storage_changed = True
            
        state.recovery_previous_distance = val_float
        
    # 3. Global distance updates
    if val_float != state.last_distance_value:
        state.last_distance_value = val_float
        state.last_distance_change_at = dt_util.as_utc(dt_util.now()).isoformat()
        storage_changed = True
        
    return storage_changed


def check_daily_rollover(state: RobotState, now: datetime) -> bool:
    """Perform daily rollover. Returns True if storage changed."""
    current_date = get_daily_date(now)
    if state.daily_date != current_date:
        state.daily_date = current_date
        state.confirmed_mowing_today = False
        state.mowing_attempted_today = False
        
        # New for 0.4.0
        state.daily_attention_required = False
        state.daily_attention_state = "not_evaluated"
        state.daily_attention_reason_codes = []
        state.daily_attention_text = None
        state.daily_attention_evaluated_at = None
        return True
    return False
