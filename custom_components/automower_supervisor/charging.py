"""Charging trend monitoring for Automower robots."""

from __future__ import annotations

from datetime import datetime

import homeassistant.util.dt as dt_util

from .models import RobotState

CHARGING_SAMPLE_MINUTES = 10
CHARGING_DECLINES_REQUIRED = 2
CHARGING_MONITOR_MAX_BATTERY = 94


def is_charging(state: RobotState) -> bool:
    """Return True when Simple Status reports charging."""
    status = state.current_status_plain or state.current_status or ""
    return status.strip().lower().startswith("charging")


def reset_charging_monitor(state: RobotState) -> bool:
    """Clear charging-monitor state and report whether anything changed."""
    changed = any(
        (
            state.charging_started_at is not None,
            state.charging_last_sample_at is not None,
            state.charging_last_sample_battery is not None,
            state.charging_decline_count != 0,
            state.charging_stalled,
            state.charging_stalled_at is not None,
        )
    )
    state.charging_started_at = None
    state.charging_last_sample_at = None
    state.charging_last_sample_battery = None
    state.charging_decline_count = 0
    state.charging_stalled = False
    state.charging_stalled_at = None
    return changed


def update_charging_monitor(state: RobotState, now: datetime) -> bool:
    """Track battery movement while Simple Status says Charging."""
    battery = state.current_battery

    if (
        not is_charging(state)
        or battery is None
        or battery > CHARGING_MONITOR_MAX_BATTERY
    ):
        return reset_charging_monitor(state)

    now_utc = dt_util.as_utc(now)
    now_iso = now_utc.isoformat()

    if (
        state.charging_last_sample_at is None
        or state.charging_last_sample_battery is None
    ):
        state.charging_started_at = state.charging_started_at or now_iso
        state.charging_last_sample_at = now_iso
        state.charging_last_sample_battery = battery
        return True

    try:
        previous_at = datetime.fromisoformat(state.charging_last_sample_at)
        elapsed_seconds = (
            now_utc - dt_util.as_utc(previous_at)
        ).total_seconds()
    except (TypeError, ValueError):
        state.charging_started_at = now_iso
        state.charging_last_sample_at = now_iso
        state.charging_last_sample_battery = battery
        state.charging_decline_count = 0
        state.charging_stalled = False
        state.charging_stalled_at = None
        return True

    if elapsed_seconds < CHARGING_SAMPLE_MINUTES * 60:
        return False

    previous_battery = state.charging_last_sample_battery

    if battery < previous_battery:
        state.charging_decline_count += 1
    elif battery > previous_battery:
        state.charging_decline_count = 0
        state.charging_stalled = False
        state.charging_stalled_at = None

    state.charging_last_sample_at = now_iso
    state.charging_last_sample_battery = battery

    if state.charging_decline_count >= CHARGING_DECLINES_REQUIRED:
        if not state.charging_stalled:
            state.charging_stalled_at = now_iso
        state.charging_stalled = True

    return True
