"""Compatibility and behavior patch for Automower Supervisor v0.5.12."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import homeassistant.util.dt as dt_util

RESET_WAIT_SECONDS = 15
VERIFY_AFTER_RESET_SECONDS = 60
REBOOT_WAIT_SECONDS = 60
VERIFY_AFTER_REBOOT_AUTO_SECONDS = 40

_INSTALLED = False


def _norm(value: Any) -> str:
    return str(value).strip().lower() if value is not None else ""


def _is_clear_value(value: Any) -> bool:
    from .const import NO_ACTIVE_ERROR_VALUES

    norm = _norm(value)
    return bool(norm and norm in NO_ACTIVE_ERROR_VALUES)


def _is_error_value(value: Any) -> bool:
    from .const import NO_ACTIVE_ERROR_VALUES

    norm = _norm(value)
    return bool(norm and norm not in NO_ACTIVE_ERROR_VALUES)


def _error_code_entity_id(robot_id: str) -> str:
    return f"sensor.{robot_id}_mower_error_code"


def _ensure_state_attrs(state: Any) -> None:
    defaults = {
        "current_error_code": None,
        "stale_error_fix_attempted_at": None,
        "stale_error_fix_incident_at": None,
        "stale_error_fix_error_message": None,
        "stale_error_fix_error_code": None,
        "stale_error_fix_result": None,
        "stale_error_fix_stage": None,
        "stale_error_fix_in_progress": False,
    }
    for key, value in defaults.items():
        if not hasattr(state, key):
            setattr(state, key, value)


def _iso_after(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    try:
        return dt_util.as_utc(datetime.fromisoformat(left)) > dt_util.as_utc(
            datetime.fromisoformat(right)
        )
    except (TypeError, ValueError):
        return False


def _stale_error_clear_evidence(state: Any) -> bool:
    status = _norm(state.current_status_plain or state.current_status)
    if status in {"error", "fault"}:
        return False

    error_text = _norm(state.current_error_message)
    if (
        "battery" in error_text
        and "empty" in error_text
        and state.current_battery is not None
        and state.current_battery >= 20
    ):
        return True

    if getattr(state, "confirmed_mowing_today", False):
        return True
    if _iso_after(getattr(state, "last_confirmed_mowing_at", None), getattr(state, "last_real_error_at", None)):
        return True
    if _iso_after(getattr(state, "last_mowing_attempt_at", None), getattr(state, "last_real_error_at", None)):
        return True

    return False


def install() -> None:
    """Install v0.5.12 monkey patches once."""
    global _INSTALLED
    if _INSTALLED:
        return

    from . import manager as manager_mod
    from . import sensor as sensor_mod

    Manager = manager_mod.AutomowerSupervisorManager
    if getattr(Manager, "_v0512_stale_error_code_patch", False):
        _INSTALLED = True
        return

    original_init = Manager.__init__

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._stale_error_code_tasks: dict[str, asyncio.Task] = {}
        for robot_id, state in self.robots.items():
            _ensure_state_attrs(state)
            self._entity_lookup[_error_code_entity_id(robot_id)] = (robot_id, "error_code")

    Manager.__init__ = patched_init

    original_load_storage = Manager._async_load_storage

    async def patched_load_storage(self, *args, **kwargs) -> bool:
        changed = await original_load_storage(self, *args, **kwargs)
        for state in self.robots.values():
            _ensure_state_attrs(state)

        stored_data = await self._storage.async_load()
        if isinstance(stored_data, dict):
            for robot_id, data in stored_data.items():
                if robot_id not in self.robots or not isinstance(data, dict):
                    continue
                state = self.robots[robot_id]
                _ensure_state_attrs(state)
                state.stale_error_fix_attempted_at = data.get("stale_error_fix_attempted_at")
                state.stale_error_fix_incident_at = data.get("stale_error_fix_incident_at")
                state.stale_error_fix_error_message = data.get("stale_error_fix_error_message")
                state.stale_error_fix_error_code = data.get("stale_error_fix_error_code")
                state.stale_error_fix_result = data.get("stale_error_fix_result")
                state.stale_error_fix_stage = data.get("stale_error_fix_stage")
                state.stale_error_fix_in_progress = False
        return changed

    Manager._async_load_storage = patched_load_storage

    original_get_storage_data = Manager.get_storage_data

    def patched_get_storage_data(self) -> dict[str, Any]:
        data = original_get_storage_data(self)
        for robot_id, state in self.robots.items():
            _ensure_state_attrs(state)
            if robot_id not in data:
                continue
            data[robot_id].update(
                {
                    "stale_error_fix_attempted_at": state.stale_error_fix_attempted_at,
                    "stale_error_fix_incident_at": state.stale_error_fix_incident_at,
                    "stale_error_fix_error_message": state.stale_error_fix_error_message,
                    "stale_error_fix_error_code": state.stale_error_fix_error_code,
                    "stale_error_fix_result": state.stale_error_fix_result,
                    "stale_error_fix_stage": state.stale_error_fix_stage,
                }
            )
        return data

    Manager.get_storage_data = patched_get_storage_data

    original_update_state_field = Manager._update_state_field

    def patched_update_state_field(self, state, key: str, value: str | None) -> bool:
        _ensure_state_attrs(state)
        if key == "error_code":
            old_value = state.current_error_code
            state.current_error_code = value
            return old_value != value
        return original_update_state_field(self, state, key, value)

    Manager._update_state_field = patched_update_state_field

    original_update_error_state = Manager._update_robot_error_state

    def patched_update_robot_error_state(self, robot_id: str, current_time_iso: str) -> bool:
        state = self.robots[robot_id]
        _ensure_state_attrs(state)

        code_clear = _is_clear_value(state.current_error_code)
        code_error = _is_error_value(state.current_error_code)
        binary_error = state.binary_error == "on"
        message_error = _is_error_value(state.current_error_message)

        if code_clear and not binary_error and message_error:
            state.stale_error_fix_error_message = state.current_error_message
            state.stale_error_fix_error_code = state.current_error_code
            state.current_error_message = "Fault 0"
        elif code_error and not message_error:
            state.current_error_message = f"Error code {state.current_error_code}"

        return original_update_error_state(self, robot_id, current_time_iso)

    Manager._update_robot_error_state = patched_update_robot_error_state

    original_sync_initial_states = Manager.sync_initial_states

    def patched_sync_initial_states(self, *args, **kwargs) -> bool:
        changed = original_sync_initial_states(self, *args, **kwargs)
        current_time_iso = dt_util.now().isoformat()

        for robot_id, state in self.robots.items():
            _ensure_state_attrs(state)
            ha_state = self.hass.states.get(_error_code_entity_id(robot_id))
            if ha_state is None:
                continue
            if ha_state.state in ("unknown", "unavailable"):
                continue
            if self._update_state_field(state, "error_code", ha_state.state):
                changed = True
            if self._update_robot_error_state(robot_id, current_time_iso):
                changed = True

        return changed

    Manager.sync_initial_states = patched_sync_initial_states

    original_buttons = Manager._robonect_button_ids

    def patched_robonect_button_ids(robot_id: str) -> dict[str, str]:
        buttons = dict(original_buttons(robot_id))
        buttons["reboot"] = f"button.{robot_id}_reboot"
        return buttons

    Manager._robonect_button_ids = staticmethod(patched_robonect_button_ids)

    def _stale_error_code_clear_eligible(self, state, now: datetime) -> bool:
        _ensure_state_attrs(state)

        if state.stale_error_fix_in_progress:
            return False
        if getattr(state, "auto_reset_in_progress", False):
            return False
        if state.current_error_active is not True:
            return False
        if state.binary_error != "off":
            return False
        if state.online is not True:
            return False
        if state.source_age_minutes is None or state.source_age_minutes > 15:
            return False
        if getattr(state, "mower_data_stale", False):
            return False
        if state.mowing_session_active:
            return False
        if not self._resting_status(state):
            return False
        if not _is_error_value(state.current_error_message):
            return False
        if not _is_error_value(state.current_error_code):
            return False

        incident_at = state.last_real_error_at
        if not incident_at:
            return False
        if state.stale_error_fix_incident_at == incident_at:
            return False
        if not _stale_error_clear_evidence(state):
            return False

        try:
            incident_dt = datetime.fromisoformat(incident_at)
            age = (dt_util.as_utc(now) - dt_util.as_utc(incident_dt)).total_seconds()
        except (TypeError, ValueError):
            return False

        return age >= manager_mod.AUTO_RESET_LATCH_MINUTES * 60

    Manager._stale_error_code_clear_eligible = _stale_error_code_clear_eligible

    def _refresh_robot_after_command(self, robot_id: str, now: datetime) -> bool:
        storage_changed = self.sync_initial_states(is_startup=False)
        self._update_watchdog_for_robot(robot_id, now)
        if self._update_robot_error_state(robot_id, dt_util.now().isoformat()):
            storage_changed = True
        return storage_changed

    Manager._refresh_robot_after_command = _refresh_robot_after_command

    async def _async_run_stale_error_code_clear(self, robot_id: str, now: datetime) -> None:
        state = self.robots[robot_id]
        _ensure_state_attrs(state)

        async with self._robot_command_lock:
            if not self._stale_error_code_clear_eligible(state, now):
                return

            buttons = self._robonect_button_ids(robot_id)
            state.stale_error_fix_in_progress = True
            state.stale_error_fix_attempted_at = dt_util.as_utc(now).isoformat()
            state.stale_error_fix_incident_at = state.last_real_error_at
            state.stale_error_fix_error_message = state.current_error_message
            state.stale_error_fix_error_code = state.current_error_code
            state.stale_error_fix_result = "in_progress"
            state.stale_error_fix_stage = "error_reset"
            await self._storage.async_save(self.get_storage_data())
            self._notify_callbacks()

            try:
                await self._async_press_robonect_button(buttons["error_reset"])
                await asyncio.sleep(RESET_WAIT_SECONDS)

                state.stale_error_fix_stage = "auto_after_reset"
                await self._async_press_robonect_button(buttons["auto"])
                await asyncio.sleep(VERIFY_AFTER_RESET_SECONDS)

                self._refresh_robot_after_command(robot_id, dt_util.now())
                if _is_clear_value(state.current_error_code):
                    state.stale_error_fix_stage = "complete"
                    state.stale_error_fix_result = "fixed_after_reset_auto"
                    return

                state.stale_error_fix_stage = "reboot"
                await self._async_press_robonect_button(buttons["reboot"])
                await asyncio.sleep(REBOOT_WAIT_SECONDS)

                state.stale_error_fix_stage = "auto_after_reboot"
                await self._async_press_robonect_button(buttons["auto"])
                await asyncio.sleep(VERIFY_AFTER_REBOOT_AUTO_SECONDS)

                self._refresh_robot_after_command(robot_id, dt_util.now())
                if _is_clear_value(state.current_error_code):
                    state.stale_error_fix_stage = "complete"
                    state.stale_error_fix_result = "fixed_after_reboot_auto"
                else:
                    state.stale_error_fix_stage = "complete"
                    state.stale_error_fix_result = "still_latched_after_reboot_auto"
            except Exception as err:
                state.stale_error_fix_result = f"command_error: {err}"
            finally:
                state.stale_error_fix_in_progress = False
                await self._storage.async_save(self.get_storage_data())
                self._notify_callbacks()

    Manager._async_run_stale_error_code_clear = _async_run_stale_error_code_clear

    def _schedule_stale_error_code_clear_if_needed(self, robot_id: str, now: datetime) -> bool:
        if not hasattr(self, "_stale_error_code_tasks"):
            self._stale_error_code_tasks = {}

        state = self.robots[robot_id]
        _ensure_state_attrs(state)
        task = self._stale_error_code_tasks.get(robot_id)
        if task is not None and not task.done():
            return False
        if not self._stale_error_code_clear_eligible(state, now):
            return False

        task = self.hass.async_create_task(
            self._async_run_stale_error_code_clear(robot_id, now)
        )
        self._stale_error_code_tasks[robot_id] = task
        return True

    Manager._schedule_stale_error_code_clear_if_needed = _schedule_stale_error_code_clear_if_needed

    original_watchdog = Manager._async_watchdog_check

    async def patched_watchdog_check(self, now: datetime) -> None:
        await original_watchdog(self, now)

        storage_changed = False
        for robot_id in self.robots:
            if self._schedule_stale_error_code_clear_if_needed(robot_id, now):
                storage_changed = True

        if storage_changed:
            self._storage.async_delay_save(self.get_storage_data, 10.0)
            self.evaluate_all_daily_attention(now)

    Manager._async_watchdog_check = patched_watchdog_check

    original_unload = Manager.async_unload

    async def patched_unload(self) -> None:
        for task in getattr(self, "_stale_error_code_tasks", {}).values():
            if not task.done():
                task.cancel()
        getattr(self, "_stale_error_code_tasks", {}).clear()
        await original_unload(self)

    Manager.async_unload = patched_unload

    original_extra_state_attributes = sensor_mod.AutomowerRobotSensor.extra_state_attributes.fget

    def patched_extra_state_attributes(self) -> dict[str, Any]:
        data = original_extra_state_attributes(self)
        state = self.manager.robots[self.robot_id]
        _ensure_state_attrs(state)
        data.update(
            {
                "current_error_code": state.current_error_code,
                "stale_error_fix_attempted_at": state.stale_error_fix_attempted_at,
                "stale_error_fix_incident_at": state.stale_error_fix_incident_at,
                "stale_error_fix_error_message": state.stale_error_fix_error_message,
                "stale_error_fix_error_code": state.stale_error_fix_error_code,
                "stale_error_fix_result": state.stale_error_fix_result,
                "stale_error_fix_stage": state.stale_error_fix_stage,
                "stale_error_fix_in_progress": state.stale_error_fix_in_progress,
            }
        )
        return data

    sensor_mod.AutomowerRobotSensor.extra_state_attributes = property(
        patched_extra_state_attributes
    )

    Manager._v0512_stale_error_code_patch = True
    _INSTALLED = True
