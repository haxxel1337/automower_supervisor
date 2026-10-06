"""Durable pause and explicit, bounded parking for the whole Supervisor."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from datetime import datetime
from functools import wraps
import logging

import homeassistant.util.dt as dt_util

from .activity import clear_pending_confirmation_fields
from .schedule import get_daily_date

_LOGGER = logging.getLogger(__name__)
WINTER_PARK_TIMEOUT_SECONDS = 15
_operation_generation = ContextVar("automower_supervisor_generation", default=None)


def supervisor_operation(func):
    """Track work and invalidate pre-pause work even if winter is later disabled."""
    @wraps(func)
    async def guarded(self, *args, **kwargs):
        if not self._supervisor_running():
            return None
        task = asyncio.current_task()
        already_tracked = task in self._supervisor_tasks
        self._supervisor_tasks.add(task)
        token = _operation_generation.set((id(self), self._supervisor_generation))
        try:
            return await func(self, *args, **kwargs)
        finally:
            _operation_generation.reset(token)
            if not already_tracked:
                self._supervisor_tasks.discard(task)
    return guarded


class WinterModeMixin:
    """Global pause state; only explicit winter parking bypasses the pause."""

    def _init_winter_mode(self):
        self.winter_mode = False
        self.winter_mode_changed_at = None
        self.winter_parking_results = {}
        self.winter_parking_in_progress = False
        self.winter_storage_error = None
        self._winter_resume_date = None
        self._winter_transition_lock = asyncio.Lock()
        self._winter_parking_task = None
        self._supervisor_tasks = set()
        self._supervisor_generation = 0
        self._supervisor_unloading = False
        self._winter_dock_tasks = set()

    def _supervisor_running(self):
        generation = _operation_generation.get()
        return (
            not self.winter_mode
            and not self._supervisor_unloading
            and (generation is None or generation[0] != id(self)
                 or generation[1] == self._supervisor_generation)
        )

    def _ensure_supervisor_running(self):
        if not self._supervisor_running():
            raise RuntimeError("Supervisor is paused by winter mode or this operation was cancelled")

    def _guarded_supervisor_service(self, handler):
        async def guarded(call):
            self._ensure_supervisor_running()
            return await self._async_supervisor_service(handler, call)
        return guarded

    @supervisor_operation
    async def _async_supervisor_service(self, handler, call):
        return await handler(call)

    def _winter_skip_catchup(self, now):
        return self._winter_resume_date == get_daily_date(now)

    def _winter_storage_data(self):
        return {
            "enabled": self.winter_mode,
            "changed_at": self.winter_mode_changed_at,
            "resume_date": self._winter_resume_date,
            "parking_results": {key: dict(value) for key, value in self.winter_parking_results.items()},
        }

    def _load_winter_state(self, data):
        """Old storage has no winter key; malformed new state must pause safely."""
        if data is None or (isinstance(data, dict) and "_winter" not in data):
            return False
        try:
            winter = data["_winter"]
            if not isinstance(winter, dict) or type(winter.get("enabled")) is not bool:
                raise ValueError("invalid winter enabled flag")
            changed_at = winter.get("changed_at")
            if changed_at is not None:
                datetime.fromisoformat(changed_at)
            resume_date = winter.get("resume_date")
            if resume_date is not None:
                datetime.strptime(resume_date, "%Y-%m-%d")
            results = winter.get("parking_results", {})
            if not isinstance(results, dict):
                raise ValueError("invalid winter parking results")
            for robot_id, result in results.items():
                if not isinstance(robot_id, str) or not isinstance(result, dict):
                    raise ValueError("invalid winter parking result")
                if result.get("status") not in {
                    "pending", "requesting", "request_completed", "failed", "unavailable", "unverified"
                }:
                    raise ValueError("invalid winter parking status")
            self.winter_mode = winter["enabled"]
            self.winter_mode_changed_at = changed_at
            self._winter_resume_date = resume_date
            self.winter_parking_results = {key: dict(value) for key, value in results.items()}
            changed = False
            for result in self.winter_parking_results.values():
                if result["status"] in {"pending", "requesting"}:
                    result["status"] = "unverified"
                    result["error"] = "Parking was interrupted; explicit retry required"
                    changed = True
            return changed
        except (KeyError, TypeError, ValueError) as err:
            self.winter_mode = True
            self.winter_storage_error = f"Invalid winter metadata: {err}"
            _LOGGER.error(self.winter_storage_error)
            return True

    async def _async_cancel_supervisor_work(self, include_parking=True):
        current = asyncio.current_task()
        tasks = set(self._supervisor_tasks)
        for name in ("_auto_reset_tasks", "_late_start_tasks", "_stale_error_code_tasks"):
            tasks.update(getattr(self, name, {}).values())
        tasks.add(getattr(self, "_morning_wakeup_task", None))
        if include_parking:
            tasks.add(self._winter_parking_task)
            tasks.update(self._winter_dock_tasks)
        tasks = {task for task in tasks if task is not None and task is not current and not task.done()}
        for task in tasks:
            task.cancel()
        if tasks:
            # Stubborn integrations cannot hold the toggle forever. Generation checks
            # prevent any later command from these invalidated operations.
            await asyncio.wait(tasks, timeout=5)
        if include_parking and self._winter_parking_task in tasks:
            for result in self.winter_parking_results.values():
                if result["status"] in {"pending", "requesting"}:
                    result["status"] = "unverified"
                    result["error"] = "Parking interrupted; explicit retry required"
            self.winter_parking_in_progress = False

    async def _async_save_winter(self):
        try:
            await self._storage.async_save_strict(self.get_storage_data())
        except Exception as err:
            self.winter_storage_error = str(err)
            self._notify_callbacks()
            raise
        self.winter_storage_error = None

    async def async_set_winter_mode(self, enabled: bool):
        if type(enabled) is not bool:
            raise ValueError("Winter mode requires a boolean")
        async with self._winter_transition_lock:
            if enabled == self.winter_mode:
                if enabled and self.winter_storage_error:
                    await self._async_save_winter()
                return
            self._supervisor_generation += 1
            if enabled:
                self.winter_mode = True
                self.winter_mode_changed_at = dt_util.as_utc(dt_util.now()).isoformat()
                self.setup_calendar_timers()
                self._prepare_winter_parking()
                self._notify_callbacks()
                try:
                    # Commit ON before waiting for cancellation or issuing HOME.
                    await self._async_save_winter()
                finally:
                    await self._async_cancel_supervisor_work()
                self._start_winter_parking()
            else:
                # Remain paused until the OFF value is durably saved.
                await self._async_cancel_supervisor_work()
                old_changed_at = self.winter_mode_changed_at
                old_resume_date = self._winter_resume_date
                self.winter_mode_changed_at = dt_util.as_utc(dt_util.now()).isoformat()
                self._winter_resume_date = get_daily_date(dt_util.now())
                # Include discarded verification state in the same durable OFF
                # transition: a restart must not count winter odometry as recovery.
                for state in self.robots.values():
                    state.mowing_session_active = False
                    state.current_mowing_segment_started_at = None
                    state.session_started_at = None
                    state.recovery_previous_distance = None
                    state.recovery_distance_baseline = None
                    state.recovery_accumulated_positive_distance = 0.0
                    clear_pending_confirmation_fields(state)
                data = self.get_storage_data()
                data["_winter"]["enabled"] = False
                try:
                    await self._storage.async_save_strict(data)
                except Exception as err:
                    self.winter_mode_changed_at = old_changed_at
                    self._winter_resume_date = old_resume_date
                    self.winter_storage_error = str(err)
                    self._notify_callbacks()
                    raise
                self.winter_mode = False
                self.winter_storage_error = None
                self.sync_initial_states(is_startup=True)
                now = dt_util.now()
                for robot_id in self.robots:
                    self._update_watchdog_for_robot(robot_id, now)
                self.evaluate_all_daily_attention(now)
                self.setup_calendar_timers()
            self._notify_callbacks()

    def _prepare_winter_parking(self):
        self.winter_parking_results = {
            robot_id: {"status": "pending", "entity_id": state.entity_ids["main"]}
            for robot_id, state in self.robots.items()
        }

    def _start_winter_parking(self):
        self.winter_parking_in_progress = True
        self._winter_parking_task = self.hass.async_create_task(
            self._async_park_for_winter(self._supervisor_generation, self.winter_parking_results)
        )
        self._notify_callbacks()

    async def async_retry_winter_parking(self):
        async with self._winter_transition_lock:
            if not self.winter_mode:
                raise RuntimeError("Enable winter mode before requesting winter parking")
            if self.winter_parking_in_progress:
                return
            self._prepare_winter_parking()
            await self._async_save_winter()
            self._start_winter_parking()

    async def _async_bounded_winter_dock(self, entity_id):
        """Bound our wait even if an integration suppresses task cancellation."""
        task = self.hass.async_create_task(self.hass.services.async_call(
            "lawn_mower", "dock", {"entity_id": entity_id}, blocking=True
        ))
        self._winter_dock_tasks.add(task)

        def finished(done):
            self._winter_dock_tasks.discard(done)
            if not done.cancelled():
                done.exception()  # Retrieve errors if a timed-out call finishes later.

        task.add_done_callback(finished)
        try:
            done, _ = await asyncio.wait({task}, timeout=WINTER_PARK_TIMEOUT_SECONDS)
            if not done:
                raise TimeoutError("Docking request timed out; physical state unverified")
            return task.result()
        finally:
            if not task.done():
                task.cancel()

    async def _async_park_for_winter(self, generation, results):
        acquired = False
        try:
            await asyncio.wait_for(self._robot_command_lock.acquire(), timeout=WINTER_PARK_TIMEOUT_SECONDS)
            acquired = True
            for robot_id, result in results.items():
                if (not self.winter_mode or self._supervisor_unloading
                        or generation != self._supervisor_generation):
                    break
                entity_id = result["entity_id"]
                entity_state = self.hass.states.get(entity_id)
                if entity_state is None or entity_state.state in {"unknown", "unavailable"}:
                    result["status"] = "unavailable"
                    result["error"] = "Entity unavailable; no docking request sent"
                    self._notify_callbacks()
                    continue
                result["status"] = "requesting"
                self._notify_callbacks()
                try:
                    await self._async_bounded_winter_dock(entity_id)
                    if generation != self._supervisor_generation:
                        break
                    result["status"] = "request_completed"
                except Exception as err:
                    result["status"] = "failed"
                    result["error"] = str(err) or type(err).__name__
                self._notify_callbacks()
        except TimeoutError:
            for result in results.values():
                if result["status"] == "pending":
                    result["status"] = "failed"
                    result["error"] = "Timed out waiting for previous commands"
        finally:
            if acquired:
                self._robot_command_lock.release()
            for result in results.values():
                if result["status"] in {"pending", "requesting"}:
                    result["status"] = "unverified"
                    result["error"] = "Parking interrupted; physical docking unverified"
            if generation == self._supervisor_generation and results is self.winter_parking_results:
                self.winter_parking_in_progress = False
                try:
                    await self._async_save_winter()
                except Exception:
                    _LOGGER.exception("Could not persist winter parking results; winter mode remains active")
                self._notify_callbacks()
