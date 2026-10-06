"""Winter mode regressions: no real Home Assistant or mower connections."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import datetime
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import test_integration as ha_stubs  # installs the shared Home Assistant stubs

from custom_components.automower_supervisor import compat_0512
from custom_components.automower_supervisor.manager import AutomowerSupervisorManager
from custom_components.automower_supervisor.models import RecoveryState


compat_0512.install()

NOW = datetime.datetime(2026, 10, 6, 12, 0, tzinfo=datetime.timezone.utc)
ROBOT = "automowerkv5"


@pytest.fixture(autouse=True)
def fixed_time():
    previous = ha_stubs.homeassistant.util.dt.now()
    ha_stubs.homeassistant.util.dt.set_time(NOW)
    yield
    ha_stubs.homeassistant.util.dt.set_time(previous)


def make_manager() -> AutomowerSupervisorManager:
    hass = MagicMock()
    hass.data = {}
    hass._mock_time_callbacks = []
    hass._mock_time_change_callbacks = []
    hass.config_entries.async_entries.return_value = []
    hass.services.async_call = AsyncMock()
    hass.services.has_service.return_value = True
    hass.async_create_task.side_effect = asyncio.create_task
    manager = AutomowerSupervisorManager(hass)
    states = {
        state.entity_ids["main"]: ha_stubs.MockState("mowing", NOW)
        for state in manager.robots.values()
    }
    states.update({
        entity: ha_stubs.MockState("ok", NOW)
        for robot_id in manager.robots
        for entity in manager._robonect_button_ids(robot_id).values()
    })
    hass.states.get.side_effect = states.get
    hass._winter_test_states = states
    return manager


async def finish_parking(manager: AutomowerSupervisorManager) -> None:
    task = manager._winter_parking_task
    if task is not None:
        await asyncio.wait_for(asyncio.shield(task), timeout=2)


async def enable_winter(manager: AutomowerSupervisorManager) -> None:
    await manager.async_set_winter_mode(True)
    await finish_parking(manager)


def service_triplets(manager: AutomowerSupervisorManager) -> list[tuple]:
    return [tuple(item.args[:3]) for item in manager.hass.services.async_call.await_args_list]


@pytest.mark.asyncio
async def test_enable_persists_before_parking_and_only_requests_home() -> None:
    manager = make_manager()
    saved: list[dict] = []
    original_save = manager._storage.async_save_strict

    async def save(data):
        saved.append(deepcopy(data))
        await original_save(data)

    async def dock(domain, service, payload, **kwargs):
        assert manager.winter_mode is True
        assert saved and saved[0]["_winter"]["enabled"] is True
        assert domain == "lawn_mower" and service == "dock"
        assert payload["entity_id"] in {
            state.entity_ids["main"] for state in manager.robots.values()
        }
        assert kwargs.get("blocking") is True

    manager._storage.async_save_strict = AsyncMock(side_effect=save)
    manager.hass.services.async_call.side_effect = dock
    await enable_winter(manager)

    assert len(service_triplets(manager)) == len(manager.robots)
    assert len({call[2]["entity_id"] for call in service_triplets(manager)}) == len(manager.robots)
    assert manager.winter_mode is True
    assert manager.winter_mode_changed_at is not None
    assert manager.winter_parking_in_progress is False
    assert set(manager.winter_parking_results) == set(manager.robots)
    assert all(
        result["status"] == "request_completed"
        for result in manager.winter_parking_results.values()
    )


@pytest.mark.asyncio
async def test_partial_parking_failure_keeps_pause_and_continues_other_robots() -> None:
    manager = make_manager()
    failed_robot, unavailable_robot = list(manager.robots)[:2]
    unavailable_entity = manager.robots[unavailable_robot].entity_ids["main"]
    manager.hass._winter_test_states[unavailable_entity] = ha_stubs.MockState("unavailable", NOW)
    failed_entity = manager.robots[failed_robot].entity_ids["main"]

    async def dock(domain, service, payload, **kwargs):
        if payload["entity_id"] == failed_entity:
            raise RuntimeError("test transport failure")

    manager.hass.services.async_call.side_effect = dock
    await enable_winter(manager)

    assert manager.winter_mode is True
    assert manager.winter_parking_in_progress is False
    assert manager.winter_parking_results[failed_robot]["status"] == "failed"
    assert manager.winter_parking_results[unavailable_robot]["status"] == "unavailable"
    assert all(
        result["status"] == "request_completed"
        for robot, result in manager.winter_parking_results.items()
        if robot not in {failed_robot, unavailable_robot}
    )
    assert all(call[:2] == ("lawn_mower", "dock") for call in service_triplets(manager))


@pytest.mark.asyncio
async def test_one_hung_parking_call_is_bounded_and_does_not_block_the_fleet(monkeypatch) -> None:
    manager = make_manager()
    winter = importlib.import_module("custom_components.automower_supervisor.winter")
    monkeypatch.setattr(winter, "WINTER_PARK_TIMEOUT_SECONDS", 0.01)
    first_robot = next(iter(manager.robots))
    first_entity = manager.robots[first_robot].entity_ids["main"]
    cancelled = asyncio.Event()

    async def dock(domain, service, payload, **kwargs):
        if payload["entity_id"] == first_entity:
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    manager.hass.services.async_call.side_effect = dock
    await enable_winter(manager)

    assert cancelled.is_set()
    assert manager.winter_mode is True
    assert manager.winter_parking_results[first_robot]["status"] == "failed"
    assert len(service_triplets(manager)) == len(manager.robots)


@pytest.mark.asyncio
async def test_storage_failure_does_not_send_parking_or_resume_routines() -> None:
    manager = make_manager()
    manager._storage.async_save_strict = AsyncMock(side_effect=OSError("disk full"))

    with pytest.raises(Exception, match="disk full"):
        await manager.async_set_winter_mode(True)

    assert manager.winter_mode is True
    assert manager.winter_parking_in_progress is False
    manager.hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_repeated_on_and_watchdog_do_not_retry_parking_but_explicit_retry_does() -> None:
    manager = make_manager()
    await enable_winter(manager)
    count = manager.hass.services.async_call.await_count
    changed_at = manager.winter_mode_changed_at

    await manager.async_set_winter_mode(True)
    await manager._async_watchdog_check(NOW)
    assert manager.hass.services.async_call.await_count == count
    assert manager.winter_mode_changed_at == changed_at

    await manager.async_retry_winter_parking()
    await finish_parking(manager)
    assert manager.hass.services.async_call.await_count == count * 2
    assert manager.winter_mode is True


@pytest.mark.asyncio
async def test_restart_restores_pause_and_results_without_automatic_repark() -> None:
    original = make_manager()
    await enable_winter(original)
    stored = deepcopy(original.get_storage_data())

    restored = make_manager()
    restored._storage._store.data = stored
    restored.sync_initial_states = MagicMock(return_value=False)
    restored.evaluate_all_daily_attention = MagicMock()
    restored.async_check_missed_syncs = AsyncMock()
    await restored.async_setup()

    assert restored.winter_mode is True
    assert restored.winter_mode_changed_at == original.winter_mode_changed_at
    assert restored.winter_parking_results == original.winter_parking_results
    assert restored.winter_parking_in_progress is False
    restored.hass.services.async_call.assert_not_awaited()
    restored.sync_initial_states.assert_not_called()
    restored.evaluate_all_daily_attention.assert_not_called()
    restored.async_check_missed_syncs.assert_not_awaited()
    await restored.async_unload()


@pytest.mark.asyncio
async def test_restart_of_interrupted_parking_never_replays_home_requests() -> None:
    manager = make_manager()
    stored = manager.get_storage_data()
    stored["_winter"] = {
        "enabled": True,
        "changed_at": NOW.isoformat(),
        "parking_results": {ROBOT: {"status": "requesting"}},
    }
    manager._storage._store.data = deepcopy(stored)

    await manager.async_setup()

    assert manager.winter_mode is True
    assert manager.winter_parking_in_progress is False
    assert manager.winter_parking_results[ROBOT]["status"] == "unverified"
    manager.hass.services.async_call.assert_not_awaited()
    await manager.async_unload()


@pytest.mark.asyncio
async def test_off_takes_fresh_snapshot_without_start_or_missed_action_replay() -> None:
    manager = make_manager()
    await enable_winter(manager)
    manager.hass.services.async_call.reset_mock()
    manager.async_check_missed_syncs = AsyncMock()
    old_error = "historical traction fault"
    manager.robots[ROBOT].last_real_error = old_error
    manager.hass._winter_test_states[manager.robots[ROBOT].entity_ids["status_plain"]] = ha_stubs.MockState("Sleeping", NOW)

    await manager.async_set_winter_mode(False)

    assert manager.winter_mode is False
    assert manager.robots[ROBOT].current_status_plain == "Sleeping"
    assert manager.robots[ROBOT].last_real_error == old_error
    assert manager.get_storage_data()["_winter"]["enabled"] is False
    manager.hass.services.async_call.assert_not_awaited()
    manager.async_check_missed_syncs.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_off_save_keeps_pause_enabled_and_does_not_send_start() -> None:
    manager = make_manager()
    await enable_winter(manager)
    manager.hass.services.async_call.reset_mock()
    manager._storage.async_save_strict = AsyncMock(side_effect=OSError("read-only storage"))

    with pytest.raises(OSError, match="read-only storage"):
        await manager.async_set_winter_mode(False)

    assert manager.winter_mode is True
    assert manager.winter_storage_error
    manager.hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("winter_data", ["broken", {"enabled": "false"}, {"enabled": True, "parking_results": []}])
async def test_invalid_winter_storage_fails_paused_without_reparking(winter_data) -> None:
    manager = make_manager()
    manager._storage._store.data = {"_winter": winter_data}

    await manager.async_setup()

    assert manager.winter_mode is True
    assert manager.winter_storage_error
    manager.hass.services.async_call.assert_not_awaited()
    await manager.async_unload()


@pytest.mark.asyncio
async def test_unreadable_storage_cannot_accidentally_resume_supervisor() -> None:
    manager = make_manager()
    manager._storage.async_load_strict = AsyncMock(side_effect=OSError("unreadable storage"))

    await manager.async_setup()

    assert manager.winter_mode is True
    assert manager.winter_storage_error
    manager.hass.services.async_call.assert_not_awaited()
    await manager.async_unload()


@pytest.mark.asyncio
async def test_retry_while_off_cannot_send_any_mower_command() -> None:
    manager = make_manager()
    try:
        await manager.async_retry_winter_parking()
    except RuntimeError:
        pass
    manager.hass.services.async_call.assert_not_awaited()
    assert manager.winter_mode is False


@pytest.mark.asyncio
@pytest.mark.parametrize("method,args", [
    ("_async_run_targeted_morning_wakeup", (NOW,)),
    ("_async_run_latched_error_reset", (ROBOT, NOW)),
    ("_async_run_late_start_kick", (ROBOT, NOW)),
    ("_async_run_stale_error_code_clear", (ROBOT, NOW)),
    ("_async_service_window_reconciliation_tick", (NOW,)),
    ("async_run_morning_calendar_sync", (NOW,)),
    ("async_run_evening_calendar_sync", (NOW,)),
    ("async_check_missed_syncs", ()),
])
async def test_routine_entry_points_do_nothing_while_paused(method, args) -> None:
    manager = make_manager()
    await enable_winter(manager)
    manager.hass.services.async_call.reset_mock()
    manager.hass.config_entries.async_entries.return_value = [SimpleNamespace(options={
        "calendar_enabled": True, "calendar_entity_id": "calendar.garden",
    })]
    # Force eligibility to expose a missing winter guard instead of passing merely
    # because an ordinary routine is ineligible in the synthetic fixture.
    for name in ("_targeted_wakeup_eligible", "_latched_error_reset_eligible", "_late_start_kick_eligible", "_stale_error_code_clear_eligible"):
        setattr(manager, name, MagicMock(return_value=True))
    before = deepcopy(manager.get_storage_data())

    await getattr(manager, method)(*args)

    manager.hass.services.async_call.assert_not_awaited()
    assert manager.get_storage_data() == before


@pytest.mark.asyncio
async def test_monitoring_and_compat_watchdog_cannot_mutate_state_or_schedule_work() -> None:
    manager = make_manager()
    await enable_winter(manager)
    manager.hass.services.async_call.reset_mock()
    for name in ("_schedule_latched_error_reset_if_needed", "_schedule_late_start_kick_if_needed", "_schedule_stale_error_code_clear_if_needed"):
        setattr(manager, name, MagicMock())
    before = deepcopy(manager.get_storage_data())
    event = ha_stubs.MockEvent(manager.robots[ROBOT].entity_ids["status_plain"], ha_stubs.MockState("Mowing", NOW))

    await manager._async_state_changed_event(event)
    await manager._async_watchdog_check(NOW)
    manager.sync_initial_states(is_startup=False)
    manager.evaluate_all_daily_attention(NOW)

    assert manager.get_storage_data() == before
    for name in ("_schedule_latched_error_reset_if_needed", "_schedule_late_start_kick_if_needed", "_schedule_stale_error_code_clear_if_needed"):
        getattr(manager, name).assert_not_called()
    manager.hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_lowest_level_button_guard_rejects_stale_caller() -> None:
    manager = make_manager()
    await enable_winter(manager)
    manager.hass.services.async_call.reset_mock()

    with pytest.raises(RuntimeError):
        await manager._async_press_robonect_button(f"button.{ROBOT}_start")

    manager.hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_calendar_service_handlers_cannot_bypass_winter_pause() -> None:
    manager = make_manager()
    await enable_winter(manager)
    manager.hass.config_entries.async_entries.return_value = [SimpleNamespace(options={
        "calendar_enabled": True, "calendar_entity_id": "calendar.garden",
    })]
    manager.register_services()
    handlers = {
        item.args[1]: item.args[2]
        for item in manager.hass.services.async_register.call_args_list
    }
    manager.async_run_morning_calendar_sync = AsyncMock()
    manager.async_run_evening_calendar_sync = AsyncMock()
    before = deepcopy(manager.get_storage_data())
    for service in ("sync_calendar", "delete_managed_calendar_event"):
        try:
            await handlers[service](SimpleNamespace(data={"mode": "morning"}))
        except RuntimeError:
            pass
    manager.async_run_morning_calendar_sync.assert_not_awaited()
    manager.async_run_evening_calendar_sync.assert_not_awaited()
    assert manager.get_storage_data() == before


@pytest.mark.asyncio
async def test_enabling_during_wakeup_sleep_cancels_following_start_and_auto(monkeypatch) -> None:
    manager = make_manager()
    for state in manager.robots.values():
        state.online = False
    state = manager.robots[ROBOT]
    state.online = True
    state.source_age_minutes = 0
    state.binary_error = "off"
    state.current_status_plain = "Charging"
    state.recovery_state = RecoveryState.NONE
    sleeping = asyncio.Event()

    async def blocked_sleep(seconds):
        sleeping.set()
        await asyncio.Event().wait()

    manager_module = importlib.import_module("custom_components.automower_supervisor.manager")
    monkeypatch.setattr(manager_module.asyncio, "sleep", blocked_sleep)
    task = asyncio.create_task(manager._async_run_targeted_morning_wakeup(NOW))
    manager._morning_wakeup_task = task
    try:
        await asyncio.wait_for(sleeping.wait(), timeout=1)
        assert service_triplets(manager) == [
            ("button", "press", {"entity_id": f"button.{ROBOT}_auto"})
        ]
        await enable_winter(manager)
        await asyncio.gather(task, return_exceptions=True)
        assert task.done()
        calls = service_triplets(manager)
        assert len(calls) == 1 + len(manager.robots)
        assert all(call[:2] == ("lawn_mower", "dock") for call in calls[1:])
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_switch_and_retry_button_use_global_device_and_explicit_manager_api() -> None:
    switch_module = importlib.import_module("custom_components.automower_supervisor.switch")
    button_module = importlib.import_module("custom_components.automower_supervisor.button")
    manager = make_manager()
    switch = switch_module.AutomowerWinterModeSwitch(manager)
    button = button_module.AutomowerWinterParkingButton(manager)
    manager.async_set_winter_mode = AsyncMock()
    manager.async_retry_winter_parking = AsyncMock()

    assert switch._attr_device_info["identifiers"] == {("automower_supervisor", "global")}
    assert button._attr_device_info["identifiers"] == switch._attr_device_info["identifiers"]
    assert switch.is_on is False
    assert button.available is False
    await switch.async_turn_on()
    await switch.async_turn_off()
    assert [item.args for item in manager.async_set_winter_mode.await_args_list] == [(True,), (False,)]

    manager.winter_mode = True
    assert switch.is_on is True
    assert button.available is True
    manager.winter_parking_in_progress = True
    assert button.available is False
    manager.winter_parking_in_progress = False
    await button.async_press()
    manager.async_retry_winter_parking.assert_awaited_once_with()
    manager.hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_entity_control_propagates_persistence_errors_without_faking_toggle() -> None:
    from custom_components.automower_supervisor.switch import AutomowerWinterModeSwitch

    manager = make_manager()
    switch = AutomowerWinterModeSwitch(manager)
    manager._storage.async_save_strict = AsyncMock(side_effect=OSError("disk full"))

    with pytest.raises(OSError, match="disk full"):
        await switch.async_turn_on()

    assert switch.is_on is True  # The in-memory fail-safe remains paused.
    manager.hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_control_platforms_add_entities_and_receive_manager_updates() -> None:
    integration = importlib.import_module("custom_components.automower_supervisor")
    switch_module = importlib.import_module("custom_components.automower_supervisor.switch")
    button_module = importlib.import_module("custom_components.automower_supervisor.button")
    assert {"sensor", "switch", "button"}.issubset(integration.PLATFORMS)
    manager = make_manager()
    entry = SimpleNamespace(runtime_data=manager)

    for module in (switch_module, button_module):
        add_entities = MagicMock()
        await module.async_setup_entry(manager.hass, entry, add_entities)
        add_entities.assert_called_once()
        entity = add_entities.call_args.args[0][0]
        # The shared minimal Entity stub is not initialized by HA's framework.
        entity._on_remove_callbacks = []
        entity.async_write_ha_state = MagicMock()
        await entity.async_added_to_hass()
        manager._notify_callbacks()
        entity.async_write_ha_state.assert_called_once()
        entity._on_remove_callbacks[0]()
        entity.async_write_ha_state.reset_mock()
        manager._notify_callbacks()
        entity.async_write_ha_state.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_resistant_old_operation_cannot_start_mower_after_off(monkeypatch) -> None:
    """A library swallowing cancellation must not outlive an ON/OFF generation."""
    manager = make_manager()
    winter = importlib.import_module("custom_components.automower_supervisor.winter")
    entered = asyncio.Event()
    release = asyncio.Event()
    cancellations = []
    original_wait = asyncio.wait

    async def bounded_test_wait(tasks, *, timeout=None, return_when=asyncio.ALL_COMPLETED):
        return await original_wait(tasks, timeout=0.01, return_when=return_when)

    monkeypatch.setattr(winter.asyncio, "wait", bounded_test_wait)

    @winter.supervisor_operation
    async def delayed_operation(self):
        entered.set()
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancellations.append(True)
        await self._async_press_robonect_button(f"button.{ROBOT}_start")

    task = asyncio.create_task(delayed_operation(manager))
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        await enable_winter(manager)
        await manager.async_set_winter_mode(False)
        manager.hass.services.async_call.reset_mock()
        assert manager.winter_mode is False
        assert cancellations
        release.set()
        with pytest.raises(RuntimeError, match="paused|cancelled"):
            await asyncio.wait_for(task, timeout=1)
        manager.hass.services.async_call.assert_not_awaited()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_paused_entities_hide_active_alerts_without_erasing_fault_history() -> None:
    from custom_components.automower_supervisor.sensor import (
        AutomowerDiscoverySensor,
        AutomowerRobotSensor,
        AutomowerSupervisorSummarySensor,
    )

    manager = make_manager()
    state = manager.robots[ROBOT]
    state.last_real_error = "No traction"
    state.current_error_active = True
    state.recovery_state = RecoveryState.ACTIVE_ERROR
    state.daily_attention_required = True
    state.daily_attention_state = "critical"
    manager.daily_attention_summary = {"attention_count": 1, "monitoring_count": 1}
    await enable_winter(manager)

    robot_sensor = AutomowerRobotSensor(ROBOT, manager)
    summary = AutomowerSupervisorSummarySensor(manager)
    discovery = AutomowerDiscoverySensor(manager)
    assert robot_sensor.native_value == "winter_mode"
    assert summary.native_value == "winter_mode"
    assert robot_sensor.extra_state_attributes["daily_attention_required"] is False
    assert robot_sensor.extra_state_attributes["assessment_reasons"] == ["WINTER_MODE"]
    assert summary.extra_state_attributes["attention_count"] == 0
    assert summary.extra_state_attributes["monitoring_count"] == 0
    assert discovery.extra_state_attributes["robots_needing_attention"] == 0
    assert summary.extra_state_attributes["calendar_sync_enabled"] is False
    assert state.last_real_error == "No traction"
    assert state.recovery_state == RecoveryState.ACTIVE_ERROR


def test_published_parking_result_snapshots_do_not_change_with_next_result() -> None:
    from custom_components.automower_supervisor.sensor import AutomowerSupervisorSummarySensor
    from custom_components.automower_supervisor.switch import AutomowerWinterModeSwitch

    manager = make_manager()
    manager.winter_parking_results = {ROBOT: {"status": "pending"}}
    switch_attributes = AutomowerWinterModeSwitch(manager).extra_state_attributes
    summary_attributes = AutomowerSupervisorSummarySensor(manager).extra_state_attributes

    manager.winter_parking_results[ROBOT]["status"] = "request_completed"

    assert switch_attributes["parking_results"][ROBOT]["status"] == "pending"
    assert summary_attributes["winter_parking_results"][ROBOT]["status"] == "pending"
