"""Constants for the Automower Supervisor integration."""

DOMAIN = "automower_supervisor"

ROBOTS = {
    "automowerkv5": "Kv5",
    "automowertuv4": "Tuv4",
    "automowervv14mini": "Vv14 Mini",
    "automowervv14big": "Vv14 Big",
    "automowervv18": "Vv18",
    "automoweralmv3": "Almv3",
    "automowerbd17": "Bd17",
    "automowersbv14": "Sbv14",
    "automowervv2": "Vv2",
    "automowertrv4": "Trv4",
    "automowerlv9": "Lv9",
}

ENTITY_PATTERNS = {
    "main": "lawn_mower.{robot}_automower",
    "status": "sensor.{robot}_mower_status",
    "status_plain": "sensor.{robot}_mower_status_plain",
    "substatus": "sensor.{robot}_mower_substatus",
    "status_duration": "sensor.{robot}_mower_status_duration",
    "battery": "sensor.{robot}_mower_battery_charge",
    "distance": "sensor.{robot}_mower_distance",
    "statistic_hours": "sensor.{robot}_mower_statistic_hours",
    "error_message": "sensor.{robot}_mower_error_message",
    "error_binary": "binary_sensor.{robot}_mower_error",
    "clock": "sensor.{robot}_clock_time",
    "battery_0": "sensor.{robot}_battery_0",
}

NO_ACTIVE_ERROR_VALUES = {
    "",
    "0",
    "fault 0",
    "none",
    "no error",
    "unknown",
    "unavailable",
}

STORAGE_KEY = "automower_supervisor.storage"
STORAGE_VERSION = 1

MOWING_SHORT_MAX_MINUTES = 3
RECOVERY_CONFIRM_MIN_MINUTES = 5
MOWING_CONFIRM_MIN_MINUTES = 10
ERROR_GRACE_PERIOD_MINUTES = 5

DISTANCE_MIN_DELTA_METERS = 1.0
RUNTIME_MIN_DELTA_HOURS = 0.01
BATTERY_MIN_DROP_PERCENT = 2

# Calendar Options Configuration
CONF_CALENDAR_ENTITY_ID = "calendar_entity_id"
CONF_CALENDAR_ENABLED = "calendar_enabled"
CONF_EVENING_SYNC_TIME = "evening_sync_time"
CONF_MORNING_SYNC_TIME = "morning_sync_time"
CONF_CALENDAR_EVENT_START_TIME = "calendar_event_start_time"
CONF_CALENDAR_EVENT_DURATION = "calendar_event_duration_minutes"

DEFAULT_EVENING_SYNC_TIME = "20:00"
DEFAULT_MORNING_SYNC_TIME = "11:20"
DEFAULT_CALENDAR_EVENT_START_TIME = "12:00"
DEFAULT_CALENDAR_EVENT_DURATION = 30

