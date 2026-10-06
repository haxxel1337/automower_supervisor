"""Calendar-only winter cleanup with simulated HA, never real mowers."""

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from test_winter_mode import NOW, enable_winter, fixed_time, make_manager
from test_integration import MockCalendarEntityFeature
from custom_components.automower_supervisor.button import AutomowerWinterCalendarCleanupButton


def event(uid="owned", day="2026-10-07", *, marked=True, title="Bot Kv5, Vv14 Mini"):
    start = datetime.fromisoformat(day).replace(hour=12, minute=20, tzinfo=timezone.utc)
    return SimpleNamespace(
        uid=uid, summary=title, start=start, end=start + timedelta(minutes=20),
        description=f"[AUTOMOWER_SUPERVISOR:v1:{day}]" if marked else "Private appointment",
        recurrence_id=None, rrule=None,
    )


def calendar_manager(events=None):
    manager = make_manager()
    manager.hass.config_entries.async_entries.return_value = [SimpleNamespace(options={
        "calendar_enabled": True, "calendar_entity_id": "calendar.garden",
    })]
    entity = SimpleNamespace(
        supported_features=MockCalendarEntityFeature.DELETE_EVENT,
        events=list(events if events is not None else [event()]),
        async_schedule_update_ha_state=MagicMock(),
    )

    async def get_events(hass, start, end):
        return [item for item in entity.events if item.start < end and item.end > start]

    async def delete_event(uid):
        entity.events[:] = [item for item in entity.events if item.uid != uid]

    entity.async_get_events = AsyncMock(side_effect=get_events)
    entity.async_delete_event = AsyncMock(side_effect=delete_event)
    manager.hass.data["calendar"] = SimpleNamespace(get_entity=lambda entity_id: entity)
    manager.event_cache = {"date": "2026-10-07", "uid": "owned"}
    manager.calendar_snapshot = SimpleNamespace(
        target_calendar_date="2026-10-07", to_dict=lambda: {"target_calendar_date": "2026-10-07"},
    )
    return manager, entity


async def finish_cleanup(manager):
    task = manager._winter_calendar_task
    if task is not None:
        await asyncio.wait_for(asyncio.shield(task), timeout=2)


@pytest.mark.asyncio
async def test_on_deletes_marked_appointments_and_duplicates_preserves_other_events():
    manager, entity = calendar_manager([
        event(), event("duplicate"), event("private", marked=False),
        event("other-bot", marked=False, title="Bot Kv5"),
    ])
    await enable_winter(manager)
    await finish_cleanup(manager)

    assert {item.uid for item in entity.events} == {"private", "other-bot"}
    assert manager.winter_calendar_cleanup["status"] == "deleted"
    assert manager.winter_calendar_cleanup["deleted_count"] == 2
    assert manager.event_cache == {}
    assert manager.calendar_snapshot is None
    entity.async_schedule_update_ha_state.assert_called_once_with(True)
    assert manager._storage._store.data["_winter"]["enabled"] is True
    assert manager._storage._store.data["_winter"]["calendar_cleanup"]["status"] == "deleted"
    assert all(call.args[:2] == ("lawn_mower", "dock") for call in manager.hass.services.async_call.await_args_list)


@pytest.mark.asyncio
async def test_upgrade_with_winter_already_on_cleans_calendar_without_any_mower_command():
    manager, entity = calendar_manager()
    stored = manager.get_storage_data()
    stored["_winter"]["enabled"] = True
    stored["_winter"].pop("calendar_cleanup")  # v0.6.0 storage
    stored["_calendar"]["evening_snapshot"] = None
    manager._storage._store.data = deepcopy(stored)

    await manager.async_setup()
    await finish_cleanup(manager)

    assert manager.winter_mode is True
    entity.async_delete_event.assert_awaited_once_with("owned")
    manager.hass.services.async_call.assert_not_awaited()
    await manager.async_unload()


@pytest.mark.asyncio
async def test_startup_waits_for_calendar_and_unload_removes_startup_listener():
    manager, entity = calendar_manager()
    manager.winter_mode = True
    manager.hass.is_running = False
    manager._schedule_winter_calendar_cleanup()
    entity.async_get_events.assert_not_awaited()
    assert manager.winter_calendar_cleanup["status"] == "waiting_startup"
    unsubscribe = manager.hass.bus.async_listen_once.return_value
    callback = manager.hass.bus.async_listen_once.call_args.args[1]
    await callback(None)
    await finish_cleanup(manager)
    entity.async_delete_event.assert_awaited_once_with("owned")

    manager.hass.is_running = False
    manager._prepare_winter_calendar()
    manager._schedule_winter_calendar_cleanup()
    await manager.async_unload()
    unsubscribe.assert_called_once()
    old_count = entity.async_get_events.await_count
    await manager.hass.bus.async_listen_once.call_args.args[1](None)
    assert entity.async_get_events.await_count == old_count


@pytest.mark.asyncio
async def test_completed_cleanup_is_not_replayed_on_reload():
    manager, entity = calendar_manager()
    await enable_winter(manager)
    await finish_cleanup(manager)
    stored = deepcopy(manager.get_storage_data())
    restored, restored_entity = calendar_manager()
    restored._storage._store.data = stored

    await restored.async_setup()
    await finish_cleanup(restored)

    assert restored.winter_calendar_cleanup["status"] == "deleted"
    restored_entity.async_get_events.assert_not_awaited()
    restored.hass.services.async_call.assert_not_awaited()
    await restored.async_unload()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["query", "delete", "unsupported", "uid", "recurrence", "missing"])
async def test_cleanup_failures_remain_paused_preserve_cache_and_allow_retry(failure):
    manager, entity = calendar_manager()
    if failure == "query":
        entity.async_get_events.side_effect = OSError("offline")
    elif failure == "delete":
        entity.async_delete_event.side_effect = OSError("cannot delete")
    elif failure == "unsupported":
        entity.supported_features = 0
    elif failure == "uid":
        entity.events[0].uid = None
    elif failure == "recurrence":
        entity.events[0].rrule = "FREQ=WEEKLY"
    else:
        manager.hass.data.pop("calendar")
    await enable_winter(manager)
    await finish_cleanup(manager)

    assert manager.winter_mode is True
    assert manager.winter_calendar_cleanup["status"] == "failed"
    assert manager.winter_calendar_cleanup["error"]
    assert manager.event_cache["date"] == "2026-10-07"
    assert entity.events
    if failure not in {"delete"}:
        entity.async_delete_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_retry_only_cleans_calendar_and_never_reparks_or_sends_start():
    manager, entity = calendar_manager()
    original_delete = entity.async_delete_event.side_effect
    entity.async_delete_event.side_effect = OSError("offline")
    await enable_winter(manager)
    await finish_cleanup(manager)
    entity.async_delete_event.side_effect = original_delete
    manager.hass.services.async_call.reset_mock()

    await manager.async_retry_winter_calendar_cleanup()
    await finish_cleanup(manager)

    assert manager.winter_calendar_cleanup["status"] == "deleted"
    manager.hass.services.async_call.assert_not_awaited()
    assert manager.event_cache == {}


@pytest.mark.asyncio
async def test_failed_pause_save_never_queries_or_deletes_calendar():
    manager, entity = calendar_manager()
    manager._storage.async_save_strict = AsyncMock(side_effect=OSError("disk full"))
    with pytest.raises(OSError, match="disk full"):
        await manager.async_set_winter_mode(True)
    assert manager.winter_mode is True
    entity.async_get_events.assert_not_awaited()
    entity.async_delete_event.assert_not_awaited()
    manager.hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_bounded_query_timeout_preserves_cache_and_reports_uncertain_cleanup(monkeypatch):
    from custom_components.automower_supervisor import winter
    manager, entity = calendar_manager()
    manager.winter_mode = True
    monkeypatch.setattr(winter, "WINTER_PARK_TIMEOUT_SECONDS", 0.01)

    async def offline(*args):
        await asyncio.Event().wait()

    entity.async_get_events.side_effect = offline
    await manager.async_retry_winter_calendar_cleanup()
    await finish_cleanup(manager)
    assert manager.winter_calendar_cleanup["status"] == "failed"
    assert "timed out" in manager.winter_calendar_cleanup["error"]
    assert manager.event_cache["date"] == "2026-10-07"
    entity.async_delete_event.assert_not_awaited()
    manager.hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_or_unconfigured_calendar_is_successful_without_deleting():
    manager, entity = calendar_manager([])
    await enable_winter(manager)
    await finish_cleanup(manager)
    assert manager.winter_calendar_cleanup["status"] == "no_events"
    entity.async_delete_event.assert_not_awaited()
    unconfigured = make_manager()
    await enable_winter(unconfigured)
    await finish_cleanup(unconfigured)
    assert unconfigured.winter_calendar_cleanup["status"] == "not_configured"


@pytest.mark.asyncio
async def test_cleanup_checks_remote_cached_date_as_well_as_current_service_week():
    manager, entity = calendar_manager([event("old", "2026-09-30"), event()])
    manager.event_cache = {"date": "2026-09-30", "uid": "old"}
    await enable_winter(manager)
    await finish_cleanup(manager)
    assert entity.async_get_events.await_count == 2
    assert manager.winter_calendar_cleanup["deleted_count"] == 2


@pytest.mark.asyncio
async def test_cancelled_query_cannot_delete_after_winter_turns_off(monkeypatch):
    manager, entity = calendar_manager()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def delayed_get(hass, start, end):
        entered.set()
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                pass
        return entity.events

    entity.async_get_events.side_effect = delayed_get
    original_wait = asyncio.wait

    async def short_wait(tasks, *, timeout=None, return_when=asyncio.ALL_COMPLETED):
        return await original_wait(tasks, timeout=0.02, return_when=return_when)

    monkeypatch.setattr(asyncio, "wait", short_wait)
    try:
        await manager.async_set_winter_mode(True)
        await asyncio.wait_for(entered.wait(), timeout=1)
        await manager.async_set_winter_mode(False)
        release.set()
        await asyncio.sleep(0)
        entity.async_delete_event.assert_not_awaited()
        assert manager.winter_mode is False
    finally:
        release.set()
        await asyncio.gather(*list(manager._winter_request_tasks), return_exceptions=True)


@pytest.mark.asyncio
async def test_cleanup_button_routes_only_to_calendar_retry_and_requires_pause():
    manager = make_manager()
    button = AutomowerWinterCalendarCleanupButton(manager)
    assert button.available is False
    with pytest.raises(RuntimeError, match="winter mode"):
        await manager.async_retry_winter_calendar_cleanup()
    manager.winter_mode = True
    assert button.available is True
    manager.winter_calendar_cleanup_in_progress = True
    assert button.available is False
    manager.winter_calendar_cleanup_in_progress = False
    manager.async_retry_winter_calendar_cleanup = AsyncMock()
    await button.async_press()
    manager.async_retry_winter_calendar_cleanup.assert_awaited_once()
    assert button._attr_device_info["identifiers"] == {("automower_supervisor", "global")}
    manager.hass.services.async_call.assert_not_awaited()
