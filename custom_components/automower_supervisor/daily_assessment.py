"""Rule-based daily attention assessment for monitored robotic mowers."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
import homeassistant.util.dt as dt_util

from .models import RobotState, RecoveryState

DAILY_CHECK_START_HOUR = 11
DAILY_CHECK_START_MINUTE = 30
DAILY_END_CHECK_HOUR = 18
DAILY_END_CHECK_MINUTE = 5


@dataclass
class DailyAttentionResult:
    """Represents the outcome of a robot's daily attention assessment."""

    required: bool
    state: str
    reason_codes: list[str] = field(default_factory=list)
    text: str = ""


def daily_check_started(now: datetime) -> bool:
    """Return True if check schedule has started local time (11:30 or later)."""
    from .schedule import SCHEDULE_TIMEZONE
    tz = dt_util.get_time_zone(SCHEDULE_TIMEZONE)
    local_now = now.astimezone(tz) if tz else dt_util.as_local(now)
    hour = local_now.hour
    minute = local_now.minute
    if hour > DAILY_CHECK_START_HOUR:
        return True
    if hour == DAILY_CHECK_START_HOUR and minute >= DAILY_CHECK_START_MINUTE:
        return True
    return False


def daily_schedule_finished(now: datetime) -> bool:
    """Return True if check schedule has finished local time (18:05 or later)."""
    from .schedule import SCHEDULE_TIMEZONE
    tz = dt_util.get_time_zone(SCHEDULE_TIMEZONE)
    local_now = now.astimezone(tz) if tz else dt_util.as_local(now)
    hour = local_now.hour
    minute = local_now.minute
    if hour > DAILY_END_CHECK_HOUR:
        return True
    if hour == DAILY_END_CHECK_HOUR and minute >= DAILY_END_CHECK_MINUTE:
        return True
    return False


def format_duration(seconds: int | None) -> str:
    """Format duration in seconds to Swedish text."""
    if seconds is None:
        return "tid saknas"
    m = seconds // 60
    s = seconds % 60
    if m > 0 and s > 0:
        return f"{m} minuter och {s} sekunder"
    if m > 0:
        return f"{m} minuter"
    return f"{s} sekunder"


def format_battery(battery: int | None) -> str:
    """Format battery percentage to Swedish text."""
    if battery is None:
        return "Batterinivå saknas"
    return f"Batteri: {battery} %"


def format_status(status: str | None) -> str:
    """Format current status to Swedish text."""
    if status is None:
        return "Aktuell status saknas"
    return f"Aktuell status: {status}"


def format_online_suffix(online: bool | None) -> str:
    """Format online suffix to Swedish text."""
    if online is True:
        return "Roboten är online."
    if online is False:
        return "Roboten är offline."
    return "Online-status kan inte avgöras."


def get_display_status(state: RobotState) -> str:
    """Return text status before numeric status, falling back to 'saknas'."""
    return (
        state.current_status_plain
        or state.current_status
        or "saknas"
    )


def is_attempt_from_today(state: RobotState, now: datetime) -> bool:
    """Return True if the last mowing attempt ended or was attempted today in Europe/Stockholm local time."""
    time_str = state.last_mowing_ended_at or state.last_mowing_attempt_at
    if not time_str:
        return False
    try:
        from .schedule import SCHEDULE_TIMEZONE
        tz = dt_util.get_time_zone(SCHEDULE_TIMEZONE)
        attempt_dt = datetime.fromisoformat(time_str)
        if attempt_dt.tzinfo is None:
            attempt_dt = dt_util.as_utc(attempt_dt)
        local_attempt = attempt_dt.astimezone(tz) if tz else dt_util.as_local(attempt_dt)
        local_now = now.astimezone(tz) if tz else dt_util.as_local(now)
        return local_attempt.date() == local_now.date()
    except Exception:
        return False


def evaluate_daily_attention(
    state: RobotState,
    now: datetime,
    observation_complete: bool,
) -> DailyAttentionResult:
    """Evaluate rules for daily attention required check for a single robot."""
    display_name = state.display_name
    status_str = get_display_status(state)
    battery_str = format_battery(state.current_battery)
    error_msg = state.last_real_error or "Okänt fel"
    online_suffix = format_online_suffix(state.online)
    attempt_is_today = is_attempt_from_today(state, now)

    # Prepare common offline template text
    if state.online is False:
        age_str = f"för {state.source_age_minutes} minuter sedan" if state.source_age_minutes is not None else "saknas"
        status_lbl = f"Senast kända status: {status_str}"
        batt_lbl = f"Senast känt batteri: {state.current_battery} %" if state.current_battery is not None else "Senast känt batteri saknas"
        offline_text = f"{display_name}: Roboten är offline. Senaste användbara uppdatering var {age_str}. {status_lbl}. {batt_lbl}."
    else:
        offline_text = ""

    # Rule 1: Aktivt eller olöst fel (always checked, not date-bound)
    is_active_error = (
        state.current_error_active
        or state.binary_error == "on"
        or state.recovery_state == RecoveryState.ACTIVE_ERROR
    )
    is_cleared_unverified = state.recovery_state == RecoveryState.CLEARED_BUT_UNVERIFIED
    is_failed_recovery = state.failed_recovery

    if is_active_error or is_cleared_unverified or is_failed_recovery:
        if is_active_error:
            code = "ACTIVE_ERROR"
            text = (
                offline_text
                if state.online is False
                else f"{display_name}: Aktivt fel \"{error_msg}\". Aktuell status: {status_str}. {battery_str}. {online_suffix}"
            )
        elif is_cleared_unverified:
            code = "CLEARED_BUT_UNVERIFIED"
            text = (
                offline_text
                if state.online is False
                else f"{display_name}: Tidigare fel \"{error_msg}\" är nollställt men inte verifierat återställt. Ingen bekräftad klippning har registrerats efter felet. Aktuell status: {status_str}. {battery_str}. {online_suffix}"
            )
        else:  # failed_recovery
            code = "FAILED_RECOVERY"
            text = (
                offline_text
                if state.online is False
                else f"{display_name}: Misslyckad återhämtning efter fel. Aktuell status: {status_str}. {battery_str}. {online_suffix}"
            )
        return DailyAttentionResult(required=True, state="needs_attention", reason_codes=[code], text=text)

    # Rule 2: Offline (always checked, not date-bound)
    if state.online is False:
        return DailyAttentionResult(
            required=True,
            state="needs_attention",
            reason_codes=["ROBOT_OFFLINE"],
            text=offline_text,
        )

    # Rule 3: Charging is reported but battery repeatedly decreases
    if state.charging_stalled:
        sampled = state.charging_last_sample_battery
        sampled_text = (
            f"Senaste batterinivå: {sampled} %."
            if sampled is not None
            else "Senaste batterinivå saknas."
        )
        text = (
            f"{display_name}: Roboten står som Charging men batteriet har "
            f"minskat vid två kontroller med minst 10 minuters mellanrum. "
            f"{sampled_text} Kontrollera kontakten mot laddstationen."
        )
        return DailyAttentionResult(
            required=True,
            state="needs_attention",
            reason_codes=["CHARGING_STALLED"],
            text=text,
        )

    # Rule 4: Gating before 11:30
    if not daily_check_started(now):
        # Om session pågår
        if state.mowing_session_active:
            text = f"{display_name}: Klippsession pågår. Bekräftelse inväntas."
            return DailyAttentionResult(
                required=False,
                state="monitoring",
                reason_codes=["MOWING_IN_PROGRESS"],
                text=text,
            )
        # Om pending confirmation finns
        if state.pending_mowing_confirmation:
            code = "RECOVERY_CONFIRMATION_PENDING" if state.pending_confirmation_type == "recovery_only" else "MOWING_CONFIRMATION_PENDING"
            text = f"{display_name}: Klippsession pågår. Bekräftelse inväntas."
            return DailyAttentionResult(
                required=False,
                state="monitoring",
                reason_codes=[code],
                text=text,
            )
        # Övriga friska robotar
        text = f"{display_name}: Ännu inte utvärderad för idag."
        return DailyAttentionResult(
            required=False,
            state="not_evaluated",
            reason_codes=[],
            text=text,
        )

    # Rule 4: Aktiv klippsession
    if state.mowing_session_active:
        text = f"{display_name}: Klippsession pågår. Bekräftelse inväntas."
        return DailyAttentionResult(
            required=False,
            state="monitoring",
            reason_codes=["MOWING_IN_PROGRESS"],
            text=text,
        )

    # Rule 5: Pending confirmation
    if state.pending_mowing_confirmation:
        code = "RECOVERY_CONFIRMATION_PENDING" if state.pending_confirmation_type == "recovery_only" else "MOWING_CONFIRMATION_PENDING"
        text = f"{display_name}: Klippsession pågår. Bekräftelse inväntas."
        return DailyAttentionResult(
            required=False,
            state="monitoring",
            reason_codes=[code],
            text=text,
        )

    # Rule 6: Bekräftad klippning idag
    if state.confirmed_mowing_today:
        text = f"{display_name}: Klippning har bekräftats idag."
        return DailyAttentionResult(
            required=False,
            state="normal",
            reason_codes=["CONFIRMED_MOWING_TODAY"],
            text=text,
        )

    # Rule 7: Incomplete daily observation guard
    if not observation_complete and not state.mowing_attempted_today:
        text = f"{display_name}: Ofullständig dagsobservation (integrationen startade efter klockan 11:30)."
        return DailyAttentionResult(
            required=False,
            state="monitoring",
            reason_codes=["INCOMPLETE_DAILY_OBSERVATION"],
            text=text,
        )

    # Rule 8: Ingen start efter 11:30
    if not state.mowing_attempted_today:
        text = f"{display_name}: Ingen klippsession har registrerats efter klockan 11:00 idag. Aktuell status: {status_str}. {battery_str}. {online_suffix}"
        return DailyAttentionResult(
            required=True,
            state="needs_attention",
            reason_codes=["DID_NOT_START"],
            text=text,
        )

    # Rule 9: Dagens specifika attempt-resultat (only if attempt_is_today is True)
    if attempt_is_today:
        # Rule 9a: Session förlorad offline
        if state.last_mowing_attempt_result == "session_lost_offline":
            text = f"{display_name}: Senaste klippsessionen gick förlorad på grund av att roboten gick offline. Aktuell status: {status_str}."
            return DailyAttentionResult(
                required=True,
                state="needs_attention",
                reason_codes=["SESSION_LOST_OFFLINE"],
                text=text,
            )

        # Rule 9b: Fel under eller efter mowing
        if state.last_mowing_attempt_result == "failed_error_during_mowing":
            text = f"{display_name}: Fel uppstod under klippning. Aktuell status: {status_str}."
            return DailyAttentionResult(
                required=True,
                state="needs_attention",
                reason_codes=["ERROR_DURING_MOWING"],
                text=text,
            )
        if state.last_mowing_attempt_result == "failed_error_after_mowing":
            text = f"{display_name}: Fel uppstod kort efter klippning. Aktuell status: {status_str}."
            return DailyAttentionResult(
                required=True,
                state="needs_attention",
                reason_codes=["ERROR_AFTER_MOWING"],
                text=text,
            )

        # Rule 9c: Kort försök
        if state.last_mowing_attempt_result == "short_attempt":
            text = f"{display_name}: Roboten gjorde endast ett kort klippförsök på {format_duration(state.last_mowing_attempt_duration_seconds)}. Ingen bekräftad klippning har registrerats idag. Aktuell status: {status_str}."
            return DailyAttentionResult(
                required=True,
                state="needs_attention",
                reason_codes=["ONLY_SHORT_ATTEMPT"],
                text=text,
            )

        # Rule 9d: Osäkert försök / Insufficient supporting data
        if state.last_mowing_attempt_result == "uncertain_attempt":
            text = f"{display_name}: Roboten gjorde ett klippförsök på {format_duration(state.last_mowing_attempt_duration_seconds)} men aktiviteten kunde inte bekräftas. Aktuell status: {status_str}."
            return DailyAttentionResult(
                required=True,
                state="needs_attention",
                reason_codes=["ONLY_UNCERTAIN_ATTEMPT"],
                text=text,
            )
        if state.last_mowing_attempt_result == "insufficient_supporting_data":
            text = f"{display_name}: Roboten gjorde ett klippförsök på {format_duration(state.last_mowing_attempt_duration_seconds)} men aktiviteten kunde inte bekräftas på grund av otillräcklig data. Aktuell status: {status_str}."
            return DailyAttentionResult(
                required=True,
                state="needs_attention",
                reason_codes=["NO_CONFIRMED_ACTIVITY"],
                text=text,
            )

        # Rule 9e: Invalid recovery confirmation
        if state.last_mowing_attempt_result == "recovery_confirmation_invalid":
            text = f"{display_name}: Roboten gjorde ett klippförsök men återställningsverifieringen misslyckades. Aktuell status: {status_str}."
            return DailyAttentionResult(
                required=True,
                state="needs_attention",
                reason_codes=["RECOVERY_CONFIRMATION_INVALID"],
                text=text,
            )

    # Rule 10: Started but not confirmed
    if state.mowing_attempted_today:
        if attempt_is_today and state.last_mowing_attempt_result == "recovery_verified_session":
            text = f"{display_name}: Det tidigare felet \"{error_msg}\" har verifierats återställt efter en klippsession på {format_duration(state.last_mowing_attempt_duration_seconds)}. Dagens fullständiga klippning är ännu inte bekräftad. Aktuell status: {status_str}."
        else:
            text = f"{display_name}: Klippning påbörjades idag men har inte bekräftats. Aktuell status: {status_str}."
        return DailyAttentionResult(
            required=True,
            state="needs_attention",
            reason_codes=["STARTED_BUT_NOT_CONFIRMED"],
            text=text,
        )

    # Default / not_evaluated
    text = f"{display_name}: Ännu inte utvärderad för idag."
    return DailyAttentionResult(
        required=False,
        state="not_evaluated",
        reason_codes=[],
        text=text,
    )
