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
