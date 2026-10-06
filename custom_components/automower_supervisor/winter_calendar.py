"""Remove this Supervisor's marked appointments while winter supervision is paused."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
import logging

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
import homeassistant.util.dt as dt_util

from .calendar_sync import get_stockholm_timezone
from .winter_calendar_log import WinterCalendarLogMixin

_LOGGER = logging.getLogger(__name__)
_FINISHED = {"deleted", "no_events", "not_configured"}


class WinterCalendarMixin(WinterCalendarLogMixin):
    """An explicit, bounded exception to the normal winter calendar pause."""

    def _init_winter_calendar(self):
        self._init_winter_calendar_log()
        self.winter_calendar_cleanup = {"status": "not_requested", "deleted_count": 0}
        self.winter_calendar_cleanup_in_progress = False
        self._winter_calendar_task = None
        self._winter_calendar_startup_unsub = None

    def _load_winter_calendar(self, winter):
        result = winter.get("calendar_cleanup", {"status": "pending", "deleted_count": 0})
        if (not isinstance(result, dict)
                or result.get("status") not in _FINISHED | {
                    "not_requested", "pending", "waiting_startup", "requesting", "failed", "interrupted"
                }
                or type(result.get("deleted_count", 0)) is not int
                or result.get("deleted_count", 0) < 0):
            raise ValueError("invalid winter calendar cleanup result")
        self.winter_calendar_cleanup = dict(result)
        if result["status"] in {"waiting_startup", "requesting"}:
            self.winter_calendar_cleanup["status"] = "interrupted"
            return True
        return False

    def _prepare_winter_calendar(self):
        self.winter_calendar_cleanup = {
            "status": "pending", "deleted_count": 0,
            "calendar_entity_id": self.calendar_entity_id,
        }

    def _cancel_winter_calendar_startup(self):
        if self._winter_calendar_startup_unsub is not None:
            self._winter_calendar_startup_unsub()
            self._winter_calendar_startup_unsub = None
            if self.winter_calendar_cleanup["status"] == "waiting_startup":
                self.winter_calendar_cleanup["status"] = "interrupted"

    def _schedule_winter_calendar_cleanup(self):
        if (not self.winter_mode or self._supervisor_unloading or self.winter_storage_error
                or self.winter_calendar_cleanup_in_progress
                or self._winter_calendar_startup_unsub is not None):
            return
        result = self.winter_calendar_cleanup
        if (result["status"] in _FINISHED
                and result.get("calendar_entity_id") == self.calendar_entity_id):
            return
        generation = self._supervisor_generation

        def start():
            if generation != self._supervisor_generation or not self.winter_mode or self._supervisor_unloading:
                return
            self._prepare_winter_calendar()
            self._start_winter_calendar_cleanup()

        if self.hass.is_running:
            start()
        else:
            self.winter_calendar_cleanup["status"] = "waiting_startup"

            async def started(_event):
                self._winter_calendar_startup_unsub = None
                start()

            self._winter_calendar_startup_unsub = self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, started
            )

    def _start_winter_calendar_cleanup(self):
        self.winter_calendar_cleanup_in_progress = True
        self._winter_calendar_task = self.hass.async_create_task(
            self._async_clean_winter_calendar(self._supervisor_generation, self.winter_calendar_cleanup)
        )
        self._notify_callbacks()

    async def async_retry_winter_calendar_cleanup(self):
        async with self._winter_transition_lock:
            if not self.winter_mode:
                raise RuntimeError("Enable winter mode before requesting calendar cleanup")
            if self.winter_calendar_cleanup_in_progress:
                return
            self._cancel_winter_calendar_startup()
            self._prepare_winter_calendar()
            await self._async_save_winter()
            self._start_winter_calendar_cleanup()

    def _winter_calendar_dates(self):
        today = dt_util.now().astimezone(get_stockholm_timezone()).date()
        dates = {today + timedelta(days=offset) for offset in range(-1, 8)}
        if self.event_cache.get("date"):
            dates.add(date.fromisoformat(self.event_cache["date"]))
        if self.calendar_snapshot is not None:
            dates.add(date.fromisoformat(self.calendar_snapshot.target_calendar_date))
        return dates

    async def _async_clean_winter_calendar(self, generation, result):
        def guard():
            if (generation != self._supervisor_generation or not self.winter_mode
                    or self._supervisor_unloading or result is not self.winter_calendar_cleanup):
                raise asyncio.CancelledError

        acquired = False
        try:
            guard()
            entity_id = result.get("calendar_entity_id")
            if not entity_id:
                result["status"] = "not_configured"
                return
            from homeassistant.components.calendar.const import CalendarEntityFeature
            component = self.hass.data.get("calendar")
            entity = component.get_entity(entity_id) if component else None
            if entity is None:
                raise RuntimeError(f"Calendar entity {entity_id} is not available; retry cleanup")
            await asyncio.wait_for(self._calendar_sync_lock.acquire(), timeout=15)
            acquired = True
            guard()
            result["status"] = "requesting"
            self._notify_callbacks()
            dates = self._winter_calendar_dates()
            # Merge adjacent days, keeping distant cached dates in separate windows.
            windows = []
            for day in sorted(dates):
                if windows and day == windows[-1][1] + timedelta(days=1):
                    windows[-1][1] = day
                else:
                    windows.append([day, day])
            tz = get_stockholm_timezone()
            owned = {}
            for first, last in windows:
                guard()
                start = datetime.combine(first, datetime.min.time(), tzinfo=tz)
                end = datetime.combine(last + timedelta(days=1), datetime.min.time(), tzinfo=tz)
                events = await self._async_bounded_winter_call(
                    entity.async_get_events(self.hass, start, end),
                    "Calendar query timed out; cleanup must be retried",
                )
                guard()
                for event in events:
                    description = event.description or ""
                    if not any(f"[AUTOMOWER_SUPERVISOR:v1:{day.isoformat()}]" in description for day in dates):
                        continue
                    if not event.uid:
                        raise RuntimeError("Marked calendar event has no UID; it was preserved")
                    if getattr(event, "recurrence_id", None) or getattr(event, "rrule", None):
                        raise RuntimeError("Marked event is recurring; it was preserved")
                    owned[event.uid] = event
            if owned and not (entity.supported_features or 0) & CalendarEntityFeature.DELETE_EVENT:
                raise RuntimeError("Calendar does not support event deletion; marked events were preserved")
            for uid in owned:
                guard()
                await self._async_bounded_winter_call(
                    entity.async_delete_event(uid),
                    "Calendar deletion timed out; outcome unverified, retry cleanup",
                )
                guard()
                result["deleted_count"] += 1
                self._notify_callbacks()
            guard()
            self.event_cache = {}
            self.calendar_snapshot = None
            self.morning_remaining_robot_ids = []
            self.morning_resolved_robot_ids = []
            result["status"] = "deleted" if owned else "no_events"
            if owned:
                # Refresh the calendar's displayed next appointment after deletion.
                refresh = getattr(entity, "async_schedule_update_ha_state", None)
                if callable(refresh):
                    refresh(True)
        except asyncio.CancelledError:
            result["status"] = "interrupted"
            raise
        except Exception as err:
            result["status"] = "failed"
            result["error"] = str(err) or type(err).__name__
            _LOGGER.warning("Winter calendar cleanup failed: %s", result["error"])
        finally:
            if acquired:
                self._calendar_sync_lock.release()
            if generation == self._supervisor_generation and result is self.winter_calendar_cleanup:
                self.winter_calendar_cleanup_in_progress = False
                result["checked_at"] = dt_util.as_utc(dt_util.now()).isoformat()
                try:
                    await self._async_save_winter()
                except Exception:
                    _LOGGER.exception("Could not persist winter calendar cleanup result")
                self._notify_callbacks()
