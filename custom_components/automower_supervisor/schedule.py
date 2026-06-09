"""Schedule tracking for the Automower Supervisor integration."""

from datetime import datetime
import homeassistant.util.dt as dt_util

SCHEDULE_START_HOUR = 11
SCHEDULE_END_HOUR = 18
SCHEDULE_TIMEZONE = "Europe/Stockholm"


def is_scheduled_now(now: datetime) -> bool:
    """Return True if the schedule is currently active (11:00 - 18:00 Europe/Stockholm)."""
    tz = dt_util.get_time_zone(SCHEDULE_TIMEZONE)
    local_now = now.astimezone(tz) if tz else dt_util.as_local(now)
    return 11 <= local_now.hour < 18


def get_daily_date(now: datetime) -> str:
    """Return the local date string (YYYY-MM-DD) in Europe/Stockholm timezone."""
    tz = dt_util.get_time_zone(SCHEDULE_TIMEZONE)
    local_now = now.astimezone(tz) if tz else dt_util.as_local(now)
    return local_now.date().isoformat()
