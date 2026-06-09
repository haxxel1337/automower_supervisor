"""Data models for the Automower Supervisor integration."""

from dataclasses import dataclass, field
from enum import StrEnum


class RecoveryState(StrEnum):
    """Recovery states for robotic lawn mowers."""

    NONE = "none"
    ACTIVE_ERROR = "active_error"
    CLEARED_BUT_UNVERIFIED = "cleared_but_unverified"
    RECOVERED = "recovered"


@dataclass
class RobotState:
    """Represents the real-time and persisted state of a single Automower robot."""

    robot_id: str
    display_name: str
    entity_ids: dict[str, str] = field(default_factory=dict)
    
    # Real-time state monitored from Home Assistant
    current_status: str | None = None
    current_status_plain: str | None = None
    current_battery: int | None = None
    current_error_message: str | None = None
    binary_error: str | None = None  # State of binary error sensor: 'on' or 'off'
    
    # Persistent tracking fields
    last_real_error: str | None = None
    last_real_error_at: str | None = None
    error_cleared_at: str | None = None
    current_error_active: bool = False
    recovery_state: RecoveryState = RecoveryState.NONE
    
    # Discovery diagnostics tracking
    missing_entities: list[str] = field(default_factory=list)
    unavailable_entities: list[str] = field(default_factory=list)
    unknown_entities: list[str] = field(default_factory=list)
    
    # Event metadata
    last_event_at: str | None = None

    # Watchdog state age tracking fields
    last_source_update_at: str | None = None
    last_heartbeat_seen_at: str | None = None
    source_age_minutes: int | None = None
    online: bool | None = None
    stale_entities: list[str] = field(default_factory=list)

    # Active Mowing Session
    mowing_session_active: bool = False
    session_started_at: str | None = None
    session_started_source: str | None = None  # "state_event" or "startup_observation"
    session_elapsed_seconds: int = 0
    accumulated_mowing_seconds: int = 0
    current_mowing_segment_started_at: str | None = None
    
    interruption_started_at: str | None = None
    interruption_status: str | None = None
    pending_session_end: bool = False
    
    session_start_battery: int | None = None
    session_start_distance: float | None = None
    session_start_runtime_hours: float | None = None
    
    session_latest_battery: int | None = None
    session_latest_distance: float | None = None
    session_latest_runtime_hours: float | None = None
    
    session_error_detected: bool = False
    session_binary_error_detected: bool = False
    session_last_mowing_ended_at: str | None = None
    pending_mowing_confirmation: bool = False

    # New session distance tracking (tolerates resets)
    session_previous_distance: float | None = None
    session_accumulated_positive_distance: float = 0.0
    session_distance_activity_detected: bool = False
    distance_reset_count: int = 0

    # New separate pending confirmation fields
    pending_confirmation_ended_at: str | None = None
    pending_confirmation_mowing_seconds: int = 0
    pending_confirmation_session_elapsed_seconds: int = 0
    pending_confirmation_distance_activity: bool = False
    pending_confirmation_runtime_activity: bool = False
    pending_confirmation_battery_activity: bool = False

    # New recovery distance tracking fields
    recovery_distance_baseline: float | None = None
    recovery_accumulated_positive_distance: float = 0.0
    recovery_previous_distance: float | None = None

    # Last Session/Attempt (Persisted)
    last_mowing_attempt_at: str | None = None
    last_mowing_attempt_duration_seconds: int | None = None
    last_mowing_session_elapsed_seconds: int | None = None
    last_mowing_attempt_result: str | None = None
    last_mowing_ended_at: str | None = None

    # Confirmed Mowing (Persisted)
    last_confirmed_mowing_at: str | None = None
    last_confirmed_mowing_duration_seconds: int | None = None
    confirmed_mowing_today: bool = False
    mowing_attempted_today: bool = False

    # Supporting Activity Tracking (Persisted)
    last_distance_value: float | None = None
    last_distance_change_at: str | None = None
    last_runtime_hours_value: float | None = None
    last_runtime_change_at: str | None = None

    # Recovery Tracking (Persisted)
    failed_recovery: bool = False
    recovery_verified_at: str | None = None
    last_real_error_category: str = "none"

    # Daily state (Persisted)
    daily_date: str | None = None
