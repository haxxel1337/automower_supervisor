"""Restart-safe winter transition log, using a simulated calendar only."""

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from test_integration import MockCalendarEntityFeature
from test_winter_mode import NOW, fixed_time, make_manager
from test_winter_calendar import calendar_manager, event, finish_cleanup
from custom_components.automower_supervisor.button import AutomowerWinterCalendarLogButton


def log_manager(events=None):
    manager, entity = calendar_manager(events)
    del manager._schedule_winter_calendar_log
    entity.supported_features |= MockCalendarEntityFeature.CREATE_EVENT

    async def service(domain, service, data, **kwargs):
        if domain == "calendar" and service == "create_event":
            item = event(f"log-{len(entity.events)}", marked=False, title=data["summary"])
            item.start = datetime.fromisoformat(data["start_date_time"])
            item.end = datetime.fromisoformat(data["end_date_time"])
            item.description = data["description"]
            entity.events.append(item)

    manager.hass.services.async_call.side_effect = service
    return manager, entity


async def finish_log(manager):
    task = manager._winter_calendar_log_task
    if task is not None:
        await asyncio.wait_for(asyncio.shield(task), timeout=2)


async def on_and_finish(manager):
    await manager.async_set_winter_mode(True)
    await finish_cleanup(manager)
    await finish_log(manager)
    await manager._winter_parking_task


def create_calls(manager):
    return [call for call in manager.hass.services.async_call.await_args_list
            if call.args[:2] == ("calendar", "create_event")]


def log_events(entity):
    return [item for item in entity.events if "[AUTOMOWER_SUPERVISOR:WINTER:v1:" in item.description]


@pytest.mark.asyncio
async def test_actual_on_off_have_one_log_each_at_transition_time_and_cleanup_preserves_them():
    manager, entity = log_manager([event(), event("personal", marked=False)])
    await on_and_finish(manager)
    await manager.async_set_winter_mode(True)  # Repeated ON is not a transition.
    await finish_log(manager)
    first = log_events(entity)[0]
    assert first.summary == "BOTS WINTER MODE ON"
    assert first.start == NOW
    assert first.end - first.start == timedelta(minutes=1)
    assert len(create_calls(manager)) == 1
    assert {item.uid for item in entity.events} == {"personal", first.uid}

    await manager.async_set_winter_mode(False)
    await finish_log(manager)
    await manager.async_set_winter_mode(False)
    await finish_log(manager)
    assert [item.summary for item in log_events(entity)] == ["BOTS WINTER MODE ON", "BOTS WINTER MODE OFF"]
    assert len(create_calls(manager)) == 2
    assert manager._storage._store.data["_winter"]["enabled"] is False
    assert all(record["status"] == "created" for record in manager.winter_calendar_log)
    await manager.async_set_winter_mode(True)
    await finish_cleanup(manager)
    await finish_log(manager)
    await manager._winter_parking_task
    assert len(log_events(entity)) == 3
    assert manager.winter_calendar_cleanup["status"] == "no_events"


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_restart_of_completed_on_or_off_never_creates_another_log(enabled):
    original, entity = log_manager([])
    await on_and_finish(original)
    if not enabled:
        await original.async_set_winter_mode(False)
        await finish_log(original)
    stored = deepcopy(original.get_storage_data())
    restored, _ = log_manager(deepcopy(entity.events))
    restored._storage._store.data = stored
    restored.async_check_missed_syncs = AsyncMock()
    await restored.async_setup()
    await finish_log(restored)
    await finish_cleanup(restored)
    assert restored.winter_mode is enabled
    assert create_calls(restored) == []
    assert len(restored.winter_calendar_log) == (1 if enabled else 2)
    await restored.async_unload()


@pytest.mark.asyncio
async def test_upgrade_records_original_on_time_once_not_startup_time():
    original, _ = log_manager([])
    stored = original.get_storage_data()
    original_time = NOW - timedelta(days=2, hours=1)
    stored["_winter"].update(enabled=True, changed_at=original_time.isoformat())
    stored["_winter"].pop("calendar_log")  # v0.6.1 metadata
    stored["_calendar"]["evening_snapshot"] = None
    original._storage._store.data = stored
    await original.async_setup()
    await finish_log(original)
    await finish_cleanup(original)
    assert len(create_calls(original)) == 1
    assert datetime.fromisoformat(create_calls(original)[0].args[2]["start_date_time"]) == original_time
    restored, _ = log_manager(deepcopy(original.hass.data["calendar"].get_entity("calendar.garden").events))
    restored._storage._store.data = deepcopy(original.get_storage_data())
    await restored.async_setup()
    await finish_log(restored)
    assert create_calls(restored) == []
    await original.async_unload()
    await restored.async_unload()


@pytest.mark.asyncio
async def test_pending_on_and_off_are_not_lost_when_calendar_is_offline():
    manager, entity = log_manager([])
    component = manager.hass.data.pop("calendar")
    await on_and_finish(manager)
    await manager.async_set_winter_mode(False)
    await finish_log(manager)
    assert [record["enabled"] for record in manager.winter_calendar_log] == [True, False]
    assert all(not record["create_attempted"] for record in manager.winter_calendar_log)
    assert create_calls(manager) == []
    manager.hass.data["calendar"] = component
    manager.hass.services.async_call.reset_mock()
    await manager.async_retry_winter_calendar_log()
    await finish_log(manager)
    assert [item.summary for item in log_events(entity)] == ["BOTS WINTER MODE ON", "BOTS WINTER MODE OFF"]
    assert len(create_calls(manager)) == 2
    assert all(call.args[0] == "calendar" for call in manager.hass.services.async_call.await_args_list)


@pytest.mark.asyncio
async def test_lost_create_response_is_reconciled_without_resending():
    manager, entity = log_manager([])
    normal_service = manager.hass.services.async_call.side_effect

    async def lost_response(domain, service, data, **kwargs):
        await normal_service(domain, service, data, **kwargs)
        if domain == "calendar":
            raise TimeoutError("lost acknowledgment")

    manager.hass.services.async_call.side_effect = lost_response
    await on_and_finish(manager)
    assert manager.winter_calendar_log[0]["status"] == "uncertain"
    assert len(log_events(entity)) == 1
    manager.hass.services.async_call.side_effect = normal_service
    await manager.async_retry_winter_calendar_log()
    await finish_log(manager)
    assert len(create_calls(manager)) == 1
    assert manager.winter_calendar_log[0]["status"] == "created"


@pytest.mark.asyncio
async def test_crash_after_create_requested_never_blindly_reissues_on_restart():
    manager, entity = log_manager([])
    manager.winter_mode = True
    record = manager._append_winter_calendar_log(True, NOW.isoformat())
    record.update(create_attempted=True, status="create_requested")
    manager._storage._store.data = deepcopy(manager.get_storage_data())
    await manager.async_setup()
    await finish_log(manager)
    await finish_cleanup(manager)
    assert manager.winter_calendar_log[0]["status"] == "uncertain"
    assert create_calls(manager) == []
    await manager.async_retry_winter_calendar_log()
    await finish_log(manager)
    assert create_calls(manager) == []
    assert log_events(entity) == []
    await manager.async_unload()


@pytest.mark.asyncio
async def test_failed_final_save_after_creation_is_reconciled_on_restart():
    manager, entity = log_manager([])
    normal_save = manager._storage.async_save_strict

    async def fail_after_created(data):
        if any(record["status"] == "created" for record in data["_winter"]["calendar_log"]):
            raise OSError("write interrupted")
        await normal_save(data)

    manager._storage.async_save_strict = AsyncMock(side_effect=fail_after_created)
    await on_and_finish(manager)
    assert len(log_events(entity)) == 1
    stored = deepcopy(manager._storage._store.data)
    assert stored["_winter"]["calendar_log"][0]["create_attempted"] is True
    restored, _ = log_manager(deepcopy(entity.events))
    restored._storage._store.data = stored
    await restored.async_setup()
    await finish_log(restored)
    assert create_calls(restored) == []
    assert restored.winter_calendar_log[0]["status"] == "created"
    await restored.async_unload()


@pytest.mark.asyncio
async def test_failed_off_transition_does_not_leave_off_log():
    manager, entity = log_manager([])
    await on_and_finish(manager)
    manager._storage.async_save_strict = AsyncMock(side_effect=OSError("disk full"))
    with pytest.raises(OSError, match="disk full"):
        await manager.async_set_winter_mode(False)
    assert manager.winter_mode is True
    assert len(manager.winter_calendar_log) == 1
    assert len(log_events(entity)) == 1
    assert log_events(entity)[0].summary == "BOTS WINTER MODE ON"


@pytest.mark.asyncio
async def test_create_requested_is_durable_before_service_and_preserves_exact_off_timestamp():
    manager, _ = log_manager([])
    original_service = manager.hass.services.async_call.side_effect

    async def service(domain, service, data, **kwargs):
        if domain == "calendar":
            stored = manager._storage._store.data["_winter"]
            assert any(record["status"] == "create_requested" and record["create_attempted"] for record in stored["calendar_log"])
            assert stored["enabled"] is manager.winter_mode
        await original_service(domain, service, data, **kwargs)

    manager.hass.services.async_call.side_effect = service
    await on_and_finish(manager)
    await manager.async_set_winter_mode(False)
    await finish_log(manager)
    off_call = create_calls(manager)[1]
    assert off_call.args[2]["summary"] == "BOTS WINTER MODE OFF"
    assert off_call.args[2]["start_date_time"] == manager.winter_mode_changed_at


@pytest.mark.asyncio
async def test_deferred_startup_log_is_cancelled_on_unload():
    manager, _ = log_manager([])
    manager.hass.is_running = False
    manager.winter_mode = True
    manager._append_winter_calendar_log(True, NOW.isoformat())
    manager._schedule_winter_calendar_log()
    callback = manager.hass.bus.async_listen_once.call_args.args[1]
    unsubscribe = manager.hass.bus.async_listen_once.return_value
    assert create_calls(manager) == []
    await manager.async_unload()
    unsubscribe.assert_called_once()
    await callback(None)
    assert create_calls(manager) == []


@pytest.mark.asyncio
async def test_deferred_log_runs_once_when_ha_has_started():
    manager, entity = log_manager([])
    manager.hass.is_running = False
    manager.winter_mode = True
    manager._append_winter_calendar_log(True, NOW.isoformat())
    manager._schedule_winter_calendar_log()
    callback = manager.hass.bus.async_listen_once.call_args.args[1]
    assert create_calls(manager) == []
    manager.hass.is_running = True
    await callback(None)
    await finish_log(manager)
    manager._schedule_winter_calendar_log()
    await finish_log(manager)
    assert len(create_calls(manager)) == 1
    assert log_events(entity)[0].start == NOW


@pytest.mark.asyncio
async def test_late_create_after_timeout_cannot_be_duplicated_by_retry(monkeypatch):
    from custom_components.automower_supervisor import winter
    manager, entity = log_manager([])
    manager.winter_mode = True
    manager._append_winter_calendar_log(True, NOW.isoformat())
    release = asyncio.Event()
    original_service = manager.hass.services.async_call.side_effect
    monkeypatch.setattr(winter, "WINTER_PARK_TIMEOUT_SECONDS", 0.01)

    async def late_response(domain, service, data, **kwargs):
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                pass
        await original_service(domain, service, data, **kwargs)

    manager.hass.services.async_call.side_effect = late_response
    try:
        await manager.async_retry_winter_calendar_log()
        await finish_log(manager)
        assert manager.winter_calendar_log[0]["status"] == "uncertain"
        await manager.async_retry_winter_calendar_log()
        await finish_log(manager)
        assert len(create_calls(manager)) == 1
        assert log_events(entity) == []
        release.set()
        await asyncio.gather(*list(manager._winter_request_tasks))
        await manager.async_retry_winter_calendar_log()
        await finish_log(manager)
        assert len(log_events(entity)) == 1
        assert len(create_calls(manager)) == 1
        assert manager.winter_calendar_log[0]["status"] == "created"
    finally:
        release.set()
        await asyncio.gather(*list(manager._winter_request_tasks), return_exceptions=True)


@pytest.mark.asyncio
async def test_log_button_only_retries_calendar_and_snapshots_are_immutable():
    manager, _ = log_manager([])
    button = AutomowerWinterCalendarLogButton(manager)
    assert button.available is False
    record = manager._append_winter_calendar_log(False, NOW.isoformat())
    assert button.available is True
    from custom_components.automower_supervisor.switch import AutomowerWinterModeSwitch
    attrs = AutomowerWinterModeSwitch(manager).extra_state_attributes
    record["status"] = "created"
    assert attrs["calendar_log"][0]["status"] == "pending"
    assert button.available is False
    manager.async_retry_winter_calendar_log = AsyncMock()
    await button.async_press()
    manager.async_retry_winter_calendar_log.assert_awaited_once()
    assert create_calls(manager) == []
