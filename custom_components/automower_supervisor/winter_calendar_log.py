"""One durable calendar logging intent for each actual winter-mode transition."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
from uuid import uuid4

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED

from .calendar_sync import get_stockholm_timezone

_LOGGER = logging.getLogger(__name__)
_STATUSES = {"pending", "not_configured", "create_requested", "created", "failed", "uncertain"}


class WinterCalendarLogMixin:
    """Persist and reconcile audit entries without reissuing uncertain creates."""

    def _init_winter_calendar_log(self):
        self.winter_calendar_log = []
        self.winter_calendar_log_in_progress = False
        self._winter_calendar_log_task = None
        self._winter_calendar_log_startup_unsub = None

    def _append_winter_calendar_log(self, enabled, changed_at):
        record = {
            "id": uuid4().hex, "enabled": enabled, "changed_at": changed_at,
            "calendar_entity_id": self.calendar_entity_id,
            "status": "pending" if self.calendar_entity_id else "not_configured",
            "create_attempted": False,
        }
        self.winter_calendar_log.append(record)
        return record

    def _load_winter_calendar_log(self, winter):
        records = winter.get("calendar_log", [])
        if not isinstance(records, list):
            raise ValueError("invalid winter calendar log")
        ids = set()
        for record in records:
            if (not isinstance(record, dict) or not isinstance(record.get("id"), str)
                    or not record["id"] or record["id"] in ids
                    or type(record.get("enabled")) is not bool
                    or type(record.get("create_attempted")) is not bool
                    or record.get("status") not in _STATUSES):
                raise ValueError("invalid winter calendar log record")
            if datetime.fromisoformat(record["changed_at"]).tzinfo is None:
                raise ValueError("winter calendar log requires a timezone")
            ids.add(record["id"])
        self.winter_calendar_log = [dict(record) for record in records]
        # Record the original activation time once when upgrading v0.6.0/0.6.1.
        if "calendar_log" not in winter and self.winter_mode and self.winter_mode_changed_at:
            self._append_winter_calendar_log(True, self.winter_mode_changed_at)
            return True
        return False

    def _cancel_winter_calendar_log_startup(self):
        if self._winter_calendar_log_startup_unsub is not None:
            self._winter_calendar_log_startup_unsub()
            self._winter_calendar_log_startup_unsub = None

    def _schedule_winter_calendar_log(self):
        if (self._supervisor_unloading or self.winter_storage_error
                or self.winter_calendar_log_in_progress
                or self._winter_calendar_log_startup_unsub is not None
                or not any(record["status"] != "created" for record in self.winter_calendar_log)
                or not self.calendar_entity_id):
            return
        generation = self._supervisor_generation

        def start():
            if generation != self._supervisor_generation or self._supervisor_unloading:
                return
            self.winter_calendar_log_in_progress = True
            self._winter_calendar_log_task = self.hass.async_create_task(
                self._async_write_winter_calendar_log(generation)
            )
            self._notify_callbacks()

        if self.hass.is_running:
            start()
        else:
            async def started(_event):
                self._winter_calendar_log_startup_unsub = None
                start()
            self._winter_calendar_log_startup_unsub = self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, started
            )

    async def async_retry_winter_calendar_log(self):
        """Retry unsent records; uncertain records are only reconciled by reading."""
        async with self._winter_transition_lock:
            if self.winter_calendar_log_in_progress:
                return
            self._cancel_winter_calendar_log_startup()
            await self._async_save_winter()
            self._schedule_winter_calendar_log()

    async def _async_write_winter_calendar_log(self, generation):
        def guard():
            if generation != self._supervisor_generation or self._supervisor_unloading:
                raise asyncio.CancelledError

        acquired = False
        try:
            await asyncio.wait_for(self._calendar_sync_lock.acquire(), timeout=15)
            acquired = True
            guard()
            for record in self.winter_calendar_log:
                if record["status"] == "created":
                    continue
                guard()
                try:
                    await self._async_write_winter_log_record(record, guard)
                except Exception as err:
                    record["status"] = "uncertain" if record["create_attempted"] else "failed"
                    record["error"] = str(err) or type(err).__name__
                    _LOGGER.warning("Winter calendar log failed: %s", record["error"])
                guard()
                await self._async_save_winter()
                self._notify_callbacks()
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Could not finish or persist winter calendar log")
        finally:
            if acquired:
                self._calendar_sync_lock.release()
            if generation == self._supervisor_generation:
                self.winter_calendar_log_in_progress = False
                self._notify_callbacks()

    async def _async_write_winter_log_record(self, record, guard):
        from homeassistant.components.calendar.const import CalendarEntityFeature

        entity_id = record.get("calendar_entity_id") or self.calendar_entity_id
        component = self.hass.data.get("calendar")
        entity = component.get_entity(entity_id) if component else None
        if entity is None:
            raise RuntimeError("Calendar unavailable; winter log can be retried")
        record["calendar_entity_id"] = entity_id
        changed_at = datetime.fromisoformat(record["changed_at"])
        local_day = changed_at.astimezone(get_stockholm_timezone()).date()
        start = datetime.combine(local_day, datetime.min.time(), tzinfo=get_stockholm_timezone())
        end = start + timedelta(days=1)
        marker = f"[AUTOMOWER_SUPERVISOR:WINTER:v1:{record['id']}]"
        guard()
        events = await self._async_bounded_winter_call(
            entity.async_get_events(self.hass, start, end),
            "Calendar query timed out; winter log can be retried",
        )
        guard()
        matches = [event for event in events if marker in (event.description or "")]
        if matches:
            record["status"] = "created"
            record["uid"] = matches[0].uid
            record.pop("error", None)
            return
        if record["create_attempted"]:
            # A lost response or a crash after this flag was saved cannot prove
            # creation failed. Never send a second create on startup or retry.
            record["status"] = "uncertain"
            record["error"] = "Creation outcome unverified; check the calendar. No duplicate create was sent."
            return
        if not (entity.supported_features or 0) & CalendarEntityFeature.CREATE_EVENT:
            raise RuntimeError("Calendar does not support event creation")
        record["create_attempted"] = True
        record["status"] = "create_requested"
        try:
            await self._async_save_winter()
        except Exception:
            record["create_attempted"] = False  # No create call was issued.
            raise
        guard()
        state = "ON" if record["enabled"] else "OFF"
        await self._async_bounded_winter_call(
            self.hass.services.async_call(
                "calendar", "create_event", {
                    "entity_id": entity_id, "summary": f"BOTS WINTER MODE {state}",
                    "description": f"Automower Supervisor winter mode {state}.\n{marker}",
                    "start_date_time": changed_at.isoformat(),
                    "end_date_time": (changed_at + timedelta(minutes=1)).isoformat(),
                }, blocking=True,
            ),
            "Calendar creation timed out; its outcome must be reconciled",
        )
        guard()
        record["status"] = "created"
        record.pop("error", None)
        refresh = getattr(entity, "async_schedule_update_ha_state", None)
        if callable(refresh):
            refresh(True)
