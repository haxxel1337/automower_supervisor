"""Calendar synchronization models, reconciliation rules, and helper methods."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
import zoneinfo

from homeassistant.core import HomeAssistant
import homeassistant.util.dt as dt_util

from .const import ROBOTS, DOMAIN
from .models import RobotState, RecoveryState

_LOGGER = logging.getLogger(__name__)


SERVICE_WEEKDAYS = {0, 2, 4}  # Monday, Wednesday, Friday


def is_service_day(value) -> bool:
    """Return True for Monday, Wednesday, or Friday."""
    return value.weekday() in SERVICE_WEEKDAYS


def get_next_service_date(
    now: datetime,
    *,
    include_current: bool,
):
    """Return the next Monday, Wednesday, or Friday service date.

    Current date is returned only when include_current is True, today is a
    service day, and local time has not passed the 11:20 reconciliation.
    """
    local_now = now.astimezone(get_stockholm_timezone())
    candidate = local_now.date()

    if include_current and is_service_day(candidate):
        if (local_now.hour, local_now.minute) <= (11, 20):
            return candidate

    candidate += timedelta(days=1)
    while not is_service_day(candidate):
        candidate += timedelta(days=1)
    return candidate


@dataclass
class CalendarRobotSnapshot:
    """Snapshot of a robot needing attention at evening sync."""

    robot_id: str
    display_name: str
    severity: str
    reason_codes: list[str]
    text: str
    captured_at: str
    current_status_plain: str | None
    current_battery: int | None
    online: bool | None
    last_real_error: str | None
    recovery_state: str
    last_mowing_attempt_result: str | None

    def to_dict(self) -> dict:
        """Serialize snapshot to dictionary."""
        return {
            "robot_id": self.robot_id,
            "display_name": self.display_name,
            "severity": self.severity,
            "reason_codes": self.reason_codes,
            "text": self.text,
            "captured_at": self.captured_at,
            "current_status_plain": self.current_status_plain,
            "current_battery": self.current_battery,
            "online": self.online,
            "last_real_error": self.last_real_error,
            "recovery_state": self.recovery_state,
            "last_mowing_attempt_result": self.last_mowing_attempt_result,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CalendarRobotSnapshot:
        """Hydrate snapshot from dictionary."""
        return cls(
            robot_id=data["robot_id"],
            display_name=data["display_name"],
            severity=data["severity"],
            reason_codes=data["reason_codes"],
            text=data["text"],
            captured_at=data["captured_at"],
            current_status_plain=data.get("current_status_plain"),
            current_battery=data.get("current_battery"),
            online=data.get("online"),
            last_real_error=data.get("last_real_error"),
            recovery_state=data.get("recovery_state", "none"),
            last_mowing_attempt_result=data.get("last_mowing_attempt_result"),
        )


@dataclass
class EveningAttentionSnapshot:
    """Snapshot of all robots needing attention captured at evening sync."""

    source_date: str
    target_calendar_date: str
    captured_at: str
    robots: list[CalendarRobotSnapshot]

    def to_dict(self) -> dict:
        """Serialize snapshot to dictionary."""
        return {
            "source_date": self.source_date,
            "target_calendar_date": self.target_calendar_date,
            "captured_at": self.captured_at,
            "robots": [r.to_dict() for r in self.robots],
        }

    @classmethod
    def from_dict(cls, data: dict) -> EveningAttentionSnapshot:
        """Hydrate snapshot from dictionary."""
        return cls(
            source_date=data["source_date"],
            target_calendar_date=data["target_calendar_date"],
            captured_at=data["captured_at"],
            robots=[CalendarRobotSnapshot.from_dict(r) for r in data.get("robots", [])],
        )


@dataclass
class MorningResolutionResult:
    """Result of morning reconciliation check for a single robot."""

    keep: bool
    resolved: bool
    reason: str
    text: str


def get_stockholm_timezone() -> zoneinfo.ZoneInfo:
    """Get Europe/Stockholm timezone object safely."""
    return dt_util.get_time_zone("Europe/Stockholm") or zoneinfo.ZoneInfo("Europe/Stockholm")


def evaluate_morning_resolution(
    snapshot: CalendarRobotSnapshot,
    current: RobotState,
    now: datetime,
) -> MorningResolutionResult:
    """Determine if a previously flagged robot's issue has been resolved."""
    keep = False
    resolved = True
    reasons_for_keeping = []

    # Common states
    is_active_or_unsolved_error = (
        current.current_error_active is True
        or current.binary_error == "on"
        or current.recovery_state in (RecoveryState.ACTIVE_ERROR, RecoveryState.CLEARED_BUT_UNVERIFIED)
        or current.failed_recovery is True
    )

    # 1. Offline rule
    if "ROBOT_OFFLINE" in snapshot.reason_codes:
        offline_resolved = (
            current.online is True
            and current.source_age_minutes is not None
            and current.source_age_minutes <= 15
            and not is_active_or_unsolved_error
            and (
                current.current_status_plain == "Mowing"
                or current.mowing_session_active is True
                or current.confirmed_mowing_today is True
            )
        )
        if not offline_resolved:
            keep = True
            resolved = False
            reasons_for_keeping.append("Roboten är fortfarande offline eller saknar bekräftad aktivitet.")

    # 2. Recovery rules
    recovery_codes = {
        "ACTIVE_ERROR",
        "CLEARED_BUT_UNVERIFIED",
        "FAILED_RECOVERY",
        "ERROR_DURING_MOWING",
        "ERROR_AFTER_MOWING",
        "RECOVERY_CONFIRMATION_INVALID",
    }
    if any(code in snapshot.reason_codes for code in recovery_codes):
        is_unsolved = (
            current.recovery_state in (RecoveryState.ACTIVE_ERROR, RecoveryState.CLEARED_BUT_UNVERIFIED)
            or current.failed_recovery is True
        )
        cond1 = (
            current.current_error_active is False
            and current.binary_error != "on"
            and current.failed_recovery is False
            and current.recovery_state == RecoveryState.RECOVERED
        )
        cond2 = (
            current.confirmed_mowing_today is True
            and not is_unsolved
        )
        if not (cond1 or cond2):
            keep = True
            resolved = False
            if current.current_status_plain == "Mowing" or current.mowing_session_active:
                reasons_for_keeping.append("Roboten klipper, men återställningen är ännu inte verifierad.")
            else:
                reasons_for_keeping.append("Roboten har ännu inte verifierats återställd efter fel.")

    # 3. Activity rules
    activity_codes = {
        "DID_NOT_START",
        "ONLY_SHORT_ATTEMPT",
        "ONLY_UNCERTAIN_ATTEMPT",
        "NO_CONFIRMED_ACTIVITY",
        "STARTED_BUT_NOT_CONFIRMED",
        "MOWING_SESSION_LOST_OFFLINE",
        "SESSION_LOST_OFFLINE",
    }
    if any(code in snapshot.reason_codes for code in activity_codes):
        active_cond = (
            current.online is True
            and current.current_error_active is False
            and current.binary_error != "on"
            and current.recovery_state not in (RecoveryState.ACTIVE_ERROR, RecoveryState.CLEARED_BUT_UNVERIFIED)
            and current.failed_recovery is False
        )
        mowing_cond = (
            current.current_status_plain == "Mowing"
            or current.mowing_session_active is True
            or current.confirmed_mowing_today is True
            or (
                current.pending_mowing_confirmation is True
                and current.pending_confirmation_type == "full_mowing"
            )
        )
        if not (active_cond and mowing_cond):
            keep = True
            resolved = False
            reasons_for_keeping.append("Roboten har ännu inte visat normal klippning idag.")

    reason_str = " ".join(reasons_for_keeping) if reasons_for_keeping else "Löst"
    return MorningResolutionResult(
        keep=keep,
        resolved=resolved,
        reason=reason_str,
        text=reason_str,
    )



def _timestamp_is_after(value: str | None, reference: str) -> bool:
    """Return True when an ISO timestamp is strictly after the reference."""
    if not value:
        return False
    try:
        value_dt = datetime.fromisoformat(value)
        reference_dt = datetime.fromisoformat(reference)
        if value_dt.tzinfo is None:
            value_dt = dt_util.as_utc(value_dt)
        if reference_dt.tzinfo is None:
            reference_dt = dt_util.as_utc(reference_dt)
        return dt_util.as_utc(value_dt) > dt_util.as_utc(reference_dt)
    except (TypeError, ValueError):
        return False


def is_snapshot_problem_resolved(
    snapshot: CalendarRobotSnapshot,
    current: RobotState,
    now: datetime,
    *,
    allow_active_activity_resolution: bool,
) -> bool:
    """Return True only when a carried service-window problem is resolved.

    Persistent timestamps are used so a successful mowing or recovery on an
    earlier day in the same service window is not lost at daily rollover.
    On the actual service-day morning, the existing live reconciliation rules
    may additionally accept active normal mowing for activity/offline cases.
    """
    codes = set(snapshot.reason_codes)
    has_unsolved_error = (
        current.current_error_active is True
        or current.binary_error == "on"
        or current.recovery_state
        in (RecoveryState.ACTIVE_ERROR, RecoveryState.CLEARED_BUT_UNVERIFIED)
        or current.failed_recovery is True
    )
    same_day_confirmed = current.confirmed_mowing_today is True
    confirmed_after_problem = _timestamp_is_after(
        current.last_confirmed_mowing_at,
        snapshot.captured_at,
    )
    confirmed_resolution = (
        not has_unsolved_error
        and (same_day_confirmed or confirmed_after_problem)
    )

    if "CHARGING_STALLED" in codes:
        return current.charging_stalled is False and not has_unsolved_error

    recovery_codes = {
        "ACTIVE_ERROR",
        "CLEARED_BUT_UNVERIFIED",
        "FAILED_RECOVERY",
        "ERROR_DURING_MOWING",
        "ERROR_AFTER_MOWING",
        "RECOVERY_CONFIRMATION_INVALID",
    }
    if codes & recovery_codes:
        recovery_after = (
            current.recovery_state == RecoveryState.RECOVERED
            and current.failed_recovery is False
            and _timestamp_is_after(
                current.recovery_verified_at,
                snapshot.captured_at,
            )
        )
        if recovery_after or confirmed_resolution:
            return True

    activity_codes = {
        "DID_NOT_START",
        "ONLY_SHORT_ATTEMPT",
        "ONLY_UNCERTAIN_ATTEMPT",
        "NO_CONFIRMED_ACTIVITY",
        "STARTED_BUT_NOT_CONFIRMED",
        "MOWING_SESSION_LOST_OFFLINE",
        "SESSION_LOST_OFFLINE",
    }
    if codes & activity_codes:
        if (
            current.online is not False
            and confirmed_resolution
        ):
            return True

    if "ROBOT_OFFLINE" in codes:
        if (
            current.online is True
            and current.source_age_minutes is not None
            and current.source_age_minutes <= 15
            and confirmed_resolution
        ):
            return True

    if allow_active_activity_resolution and "CHARGING_STALLED" not in codes:
        return evaluate_morning_resolution(snapshot, current, now).resolved

    return False


def reconcile_service_window_snapshot(
    existing_snapshot: EveningAttentionSnapshot | None,
    target_calendar_date: str,
    current_states: dict[str, RobotState],
    current_problem_snapshots: list[CalendarRobotSnapshot],
    now: datetime,
    *,
    allow_active_activity_resolution: bool = False,
) -> tuple[list[CalendarRobotSnapshot], list[str]]:
    """Reconcile carried problems and merge current problems for one window."""
    retained: dict[str, CalendarRobotSnapshot] = {}
    resolved_robot_ids: list[str] = []

    if (
        existing_snapshot is not None
        and existing_snapshot.target_calendar_date == target_calendar_date
    ):
        for robot in existing_snapshot.robots:
            current = current_states.get(robot.robot_id)
            if current is None:
                retained[robot.robot_id] = robot
                continue
            if is_snapshot_problem_resolved(
                robot,
                current,
                now,
                allow_active_activity_resolution=(
                    allow_active_activity_resolution
                ),
            ):
                resolved_robot_ids.append(robot.robot_id)
            else:
                retained[robot.robot_id] = robot

    # Current problems always win for the same robot. This also gives a new
    # incident a fresh captured_at while carried problems keep their original
    # timestamp for persistent resolution comparisons.
    for robot in current_problem_snapshots:
        retained[robot.robot_id] = robot
        if robot.robot_id in resolved_robot_ids:
            resolved_robot_ids.remove(robot.robot_id)

    return list(retained.values()), resolved_robot_ids


def get_evening_problem_desc(snapshot: CalendarRobotSnapshot) -> str:
    """Return a clean Swedish explanation of the evening problem."""
    code = snapshot.reason_codes[0] if snapshot.reason_codes else ""
    if code == "DID_NOT_START":
        return "Ingen klippsession har registrerats efter klockan 11:00 idag."
    elif code == "ONLY_SHORT_ATTEMPT":
        # Extract duration if present
        text = snapshot.text
        if "kort klippförsök på" in text:
            try:
                part = text.split("kort klippförsök på")[1].split(".")[0].strip()
                return f"Endast ett kort klippförsök på {part}."
            except Exception:
                pass
        return "Endast ett kort klippförsök."
    elif code == "ONLY_UNCERTAIN_ATTEMPT":
        text = snapshot.text
        if "klippförsök på" in text:
            try:
                part = text.split("klippförsök på")[1].split("men")[0].strip()
                return f"Roboten gjorde ett klippförsök på {part} men aktiviteten kunde inte bekräftas."
            except Exception:
                pass
        return "Roboten gjorde ett klippförsök men aktiviteten kunde inte bekräftas."
    elif code == "NO_CONFIRMED_ACTIVITY":
        return "Roboten gjorde ett klippförsök men aktiviteten kunde inte bekräftas på grund av otillräcklig data."
    elif code == "STARTED_BUT_NOT_CONFIRMED":
        return "Klippning påbörjades idag men har inte bekräftats."
    elif code in ("SESSION_LOST_OFFLINE", "MOWING_SESSION_LOST_OFFLINE"):
        return "Senaste klippsessionen gick förlorad på grund av att roboten gick offline."
    elif code == "ACTIVE_ERROR":
        err_msg = snapshot.last_real_error or "Okänt fel"
        return f"Aktivt fel \"{err_msg}\"."
    elif code == "CLEARED_BUT_UNVERIFIED":
        err_msg = snapshot.last_real_error or "Okänt fel"
        return f"Tidigare fel \"{err_msg}\" var nollställt men inte verifierat återställt."
    elif code == "FAILED_RECOVERY":
        return "Misslyckad återhämtning efter fel."
    elif code == "ERROR_DURING_MOWING":
        return "Fel uppstod under klippning."
    elif code == "ERROR_AFTER_MOWING":
        return "Fel uppstod kort efter klippning."
    elif code == "RECOVERY_CONFIRMATION_INVALID":
        return "Roboten gjorde ett klippförsök men återställningsverifieringen misslyckades."
    elif code == "ROBOT_OFFLINE":
        return "Roboten är offline."
    else:
        text = snapshot.text
        prefix = f"{snapshot.display_name}: "
        if text.startswith(prefix):
            return text[len(prefix):]
        return text


def build_calendar_description(
    robots_data: list[dict],
    sync_time_str: str,
    date_str: str,
    is_morning: bool = False,
) -> str:
    """Build the deterministic Swedish worklist description for the calendar event."""
    count = len(robots_data)
    if count == 0:
        return ""

    if is_morning:
        lbl = "robotar behöver fortfarande ses över." if count > 1 else "robot behöver fortfarande ses över."
    else:
        lbl = "robotar behöver ses över." if count > 1 else "robot behöver ses över."

    lines = [f"{count} {lbl}", ""]

    for r in robots_data:
        lines.append(r["display_name"])
        if is_morning:
            lines.append(f"Kvällens problem: {r['evening_text']}")
            lines.append(f"Morgonstatus 11:20: {r['current_status']}.")
            if r.get("recovery_state") and r["recovery_state"] != "none":
                lines.append(f"Recovery state: {r['recovery_state']}.")
            if r.get("battery") is not None:
                lines.append(f"Batteri: {r['battery']} %.")
            lines.append(r["morning_status_text"])
        else:
            # Evening description:
            # Remove robot name from snapshot text prefix if it exists to make it clean
            lines.append(r["evening_text"])
            lines.append(f"Kvällsstatus: {r['current_status']}.")
            if r.get("battery") is not None:
                lines.append(f"Kvällsbatteri: {r['battery']} %.")

        lines.append("")

    lines.append(f"Senast synkroniserad: {sync_time_str}.")
    lines.append("Automatiskt skapad av Automower Supervisor.")
    lines.append("")
    lines.append(f"[AUTOMOWER_SUPERVISOR:v1:{date_str}]")

    return "\n".join(lines)


async def async_fetch_managed_event(
    hass: HomeAssistant,
    calendar_entity_id: str,
    date_str: str,
) -> dict | None:
    """Search for an existing managed event in the narrow window of target date."""
    try:
        # Define search boundaries (00:00 to 23:59:59 local Stockholm date)
        tz = get_stockholm_timezone()
        dt_start = datetime.fromisoformat(f"{date_str}T00:00:00").replace(tzinfo=tz)
        dt_end = dt_start + timedelta(days=1)

        # Retrieve entities from calendar component
        component = hass.data.get("calendar")
        if not component:
            _LOGGER.warning("Calendar component not registered in hass.data")
            return None

        entity = component.get_entity(calendar_entity_id)
        if not entity:
            _LOGGER.warning("Calendar entity %s not found in EntityComponent", calendar_entity_id)
            return None

        # Query events using entity async_get_events
        events = await entity.async_get_events(hass, dt_start, dt_end)
        if not events:
            return None

        marker = f"[AUTOMOWER_SUPERVISOR:v1:{date_str}]"
        matched_events = []

        for event in events:
            desc = event.description or ""
            if marker in desc:
                matched_events.append(event)

        if not matched_events:
            return None

        # Clean duplicates if multiple matched
        if len(matched_events) > 1:
            _LOGGER.warning(
                "Multiple managed events found for date %s in calendar %s. Cleaning up duplicates...",
                date_str,
                calendar_entity_id,
            )
            # Keep the first one, delete the rest
            for extra_event in matched_events[1:]:
                if extra_event.uid:
                    try:
                        await entity.async_delete_event(extra_event.uid)
                    except Exception as err:
                        _LOGGER.error("Failed to delete duplicate calendar event: %s", err)

        event_match = matched_events[0]
        return {
            "uid": event_match.uid,
            "summary": event_match.summary,
            "description": event_match.description,
            "start": event_match.start,
            "end": event_match.end,
        }
    except Exception as err:
        _LOGGER.error("Error fetching managed event from calendar: %s", err)
        raise err
