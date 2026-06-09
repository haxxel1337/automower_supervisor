"""Tests for the Automower Supervisor custom integration."""

# ruff: noqa: E402
from __future__ import annotations

import datetime
import sys
from types import ModuleType
from typing import Any, Callable
from unittest.mock import MagicMock, AsyncMock

# ==========================================
# HOME ASSISTANT STUBS AND MOCK ENVIRONMENT
# ==========================================

class MockEntity:
    """Mock base class for Home Assistant Entity."""
    def __init__(self) -> None:
        self.hass: Any = None
        self.entity_id: str | None = None
        self._on_remove_callbacks: list[Callable[[], None]] = []

    def async_on_remove(self, func: Callable[[], None]) -> None:
        """Register removal callback."""
        self._on_remove_callbacks.append(func)

    def async_write_ha_state(self) -> None:
        """Simulate writing state to HA."""
        pass


class MockSensorEntity(MockEntity):
    """Mock class for SensorEntity."""
    pass


class MockDeviceInfo(dict):
    """Mock class for DeviceInfo."""
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(kwargs)


# Create and register dummy Home Assistant modules
for mod_name in [
    "homeassistant",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.config_entries",
    "homeassistant.helpers",
    "homeassistant.helpers.storage",
    "homeassistant.helpers.event",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.entity_platform",
    "homeassistant.components",
    "homeassistant.components.sensor",
    "homeassistant.util",
    "homeassistant.util.dt",
    "homeassistant.data_entry_flow",
]:
    sys.modules[mod_name] = ModuleType(mod_name)

# Bind modules as attributes of parent modules so sub-imports work
import homeassistant
import homeassistant.helpers
import homeassistant.components

homeassistant.const = sys.modules["homeassistant.const"]
homeassistant.core = sys.modules["homeassistant.core"]
homeassistant.config_entries = sys.modules["homeassistant.config_entries"]
homeassistant.helpers = sys.modules["homeassistant.helpers"]
homeassistant.helpers.storage = sys.modules["homeassistant.helpers.storage"]
homeassistant.helpers.event = sys.modules["homeassistant.helpers.event"]
homeassistant.helpers.device_registry = sys.modules["homeassistant.helpers.device_registry"]
homeassistant.helpers.entity_platform = sys.modules["homeassistant.helpers.entity_platform"]
homeassistant.components = sys.modules["homeassistant.components"]
homeassistant.components.sensor = sys.modules["homeassistant.components.sensor"]
homeassistant.util = sys.modules["homeassistant.util"]
homeassistant.util.dt = sys.modules["homeassistant.util.dt"]
homeassistant.data_entry_flow = sys.modules["homeassistant.data_entry_flow"]
homeassistant.data_entry_flow.FlowResult = dict

# Setup homeassistant.const
import homeassistant.const
homeassistant.const.Platform = MagicMock()
homeassistant.const.Platform.SENSOR = "sensor"

# Setup homeassistant.core
import homeassistant.core
homeassistant.core.HomeAssistant = MagicMock
homeassistant.core.Event = MagicMock

# Setup homeassistant.config_entries
import homeassistant.config_entries
class MockConfigEntry:
    def __init__(self, entry_id: str = "test_entry_id") -> None:
        self.entry_id = entry_id
        self.runtime_data = None
homeassistant.config_entries.ConfigEntry = MockConfigEntry

class MockConfigFlow:
    def __init_subclass__(cls, domain=None, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.domain = domain

    async def async_set_unique_id(self, unique_id):
        self.unique_id = unique_id
        return unique_id

    def _abort_if_unique_id_configured(self):
        pass

    def async_abort(self, reason):
        return {"type": "abort", "reason": reason}

    def async_create_entry(self, title, data):
        return {"type": "create_entry", "title": title, "data": data}

    def async_show_form(self, step_id, data_schema):
        return {"type": "form", "step_id": step_id, "data_schema": data_schema}

homeassistant.config_entries.ConfigFlow = MockConfigFlow

# Setup homeassistant.helpers.storage
import homeassistant.helpers.storage
class MockStore:
    def __init__(self, hass: Any, version: int, key: str) -> None:
        self.hass = hass
        self.version = version
        self.key = key
        self.data: dict[str, Any] | None = None

    def __class_getitem__(cls, item):
        return cls

    async def async_load(self) -> dict[str, Any] | None:
        return self.data

    async def async_save(self, data: dict[str, Any]) -> None:
        self.data = data

    def async_delay_save(self, callback: Callable[[], dict[str, Any]], delay: float) -> None:
        self.data = callback()

homeassistant.helpers.storage.Store = MockStore

# Setup homeassistant.helpers.event
import homeassistant.helpers.event
def mock_async_track_state_change_event(hass: Any, entity_ids: list[str], action: Callable[[Any], None]) -> MagicMock:
    unsub = MagicMock()
    return unsub
homeassistant.helpers.event.async_track_state_change_event = mock_async_track_state_change_event

def mock_async_track_time_interval(hass: Any, action: Callable[[Any], None], interval: Any) -> MagicMock:
    unsub = MagicMock()
    if not hasattr(hass, "_mock_time_callbacks"):
        hass._mock_time_callbacks = []
    hass._mock_time_callbacks.append((action, interval))
    return unsub
homeassistant.helpers.event.async_track_time_interval = mock_async_track_time_interval

# Setup homeassistant.helpers.device_registry
import homeassistant.helpers.device_registry
homeassistant.helpers.device_registry.DeviceInfo = MockDeviceInfo

# Setup homeassistant.helpers.entity_platform
import homeassistant.helpers.entity_platform
homeassistant.helpers.entity_platform.AddEntitiesCallback = MagicMock

# Setup homeassistant.components.sensor
import homeassistant.components.sensor
homeassistant.components.sensor.SensorEntity = MockSensorEntity

# Setup homeassistant.util.dt
import homeassistant.util.dt
class MockDt:
    def __init__(self) -> None:
        self.current_time = datetime.datetime(2026, 6, 9, 9, 15, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=2)))

    def now(self) -> datetime.datetime:
        return self.current_time

    def set_time(self, dt: datetime.datetime) -> None:
        self.current_time = dt

    def as_utc(self, dt: datetime.datetime) -> datetime.datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc)

    def get_time_zone(self, tz_name: str) -> datetime.tzinfo | None:
        import zoneinfo
        try:
            return zoneinfo.ZoneInfo(tz_name)
        except Exception:
            return datetime.timezone(datetime.timedelta(hours=2))

    def as_local(self, dt: datetime.datetime) -> datetime.datetime:
        tz = self.get_time_zone("Europe/Stockholm")
        if dt.tzinfo is None:
            return dt.replace(tzinfo=tz)
        return dt.astimezone(tz)
homeassistant.util.dt = MockDt()

# ==========================================
# IMPORTING THE INTEGRATION MODULES
# ==========================================
from custom_components.automower_supervisor.models import RecoveryState  # noqa: E402
from custom_components.automower_supervisor.manager import AutomowerSupervisorManager  # noqa: E402
from custom_components.automower_supervisor.sensor import AutomowerRobotSensor, AutomowerDiscoverySensor  # noqa: E402
from custom_components.automower_supervisor.config_flow import AutomowerSupervisorConfigFlow  # noqa: E402

# ==========================================
# UNIT TESTS
# ==========================================

import pytest

class MockState:
    def __init__(self, state_value: str, last_updated: datetime.datetime | None = None) -> None:
        self.state = state_value
        self.last_updated = last_updated or homeassistant.util.dt.now()

class MockEvent:
    def __init__(self, entity_id: str, new_state: MockState | None, old_state: MockState | None = None) -> None:
        self.data = {
            "entity_id": entity_id,
            "new_state": new_state,
            "old_state": old_state
        }


@pytest.mark.asyncio
async def test_config_flow() -> None:
    """Test config flow behaves correctly."""
    flow = AutomowerSupervisorConfigFlow()
    flow.hass = MagicMock()
    flow._async_current_entries = MagicMock(return_value=[])
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()

    # Step user initialization (no input)
    res = await flow.async_step_user()
    assert res["type"] == "form"
    assert res["step_id"] == "user"

    # Step user submission
    res_submit = await flow.async_step_user(user_input={})
    assert res_submit["type"] == "create_entry"
    assert res_submit["title"] == "Automower Supervisor"
    assert res_submit["data"] == {}

    # Duplicate block
    flow._async_current_entries = MagicMock(return_value=[MockConfigEntry()])
    res_dup = await flow.async_step_user()
    assert res_dup["type"] == "abort"
    assert res_dup["reason"] == "already_configured"


@pytest.mark.asyncio
async def test_manager_setup_and_unload() -> None:
    """Test manager registers entities, hooks, and clean shutdowns."""
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    
    manager = AutomowerSupervisorManager(hass)
    await manager.async_setup()
    
    # 11 robots initialized
    assert len(manager.robots) == 11
    assert "automowerkv5" in manager.robots
    
    # Test callbacks mechanism
    called = False
    def test_cb() -> None:
        nonlocal called
        called = True
        
    unsub = manager.async_register_callback(test_cb)
    manager._notify_callbacks()
    assert called
    
    # Safe double unsubscribe (should not raise ValueError)
    unsub()
    unsub()
    
    # Check unload
    await manager.async_unload()
    assert manager._unsub_listener is None
    assert len(manager._callbacks) == 0


@pytest.mark.asyncio
async def test_error_timestamp_behavior() -> None:
    """Test last_real_error_at timestamp updates only on new error incident."""
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    
    homeassistant.util.dt.set_time(datetime.datetime(2026, 6, 9, 15, 40, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=2))))
    manager = AutomowerSupervisorManager(hass)
    await manager.async_setup()
    
    robot_id = "automowerkv5"
    state = manager.robots[robot_id]
    
    # 1. New error: sets last_real_error_at
    event1 = MockEvent("sensor.automowerkv5_mower_error_message", MockState("Blade disc blocked"))
    await manager._async_state_changed_event(event1)
    
    assert state.current_error_active is True
    assert state.last_real_error == "Blade disc blocked"
    t1 = state.last_real_error_at
    assert t1 is not None
    
    # 2. Battery update: should NOT change timestamp
    homeassistant.util.dt.set_time(datetime.datetime(2026, 6, 9, 15, 45, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=2))))
    event2 = MockEvent("sensor.automowerkv5_mower_battery_charge", MockState("98"))
    await manager._async_state_changed_event(event2)
    assert state.last_real_error_at == t1
    
    # 3. Status update: should NOT change timestamp
    homeassistant.util.dt.set_time(datetime.datetime(2026, 6, 9, 15, 47, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=2))))
    event3 = MockEvent("sensor.automowerkv5_mower_status", MockState("Mowing"))
    await manager._async_state_changed_event(event3)
    assert state.last_real_error_at == t1

    # 4. Same error message update: should NOT change timestamp
    homeassistant.util.dt.set_time(datetime.datetime(2026, 6, 9, 15, 48, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=2))))
    event4 = MockEvent("sensor.automowerkv5_mower_error_message", MockState("Blade disc blocked"))
    await manager._async_state_changed_event(event4)
    assert state.last_real_error_at == t1

    # 5. New DIFFERENT error message: updates timestamp
    homeassistant.util.dt.set_time(datetime.datetime(2026, 6, 9, 15, 50, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=2))))
    event5 = MockEvent("sensor.automowerkv5_mower_error_message", MockState("No traction"))
    await manager._async_state_changed_event(event5)
    t2 = state.last_real_error_at
    assert t2 != t1
    assert state.last_real_error == "No traction"

    # 6. Fault 0 does not erase/change error message or error timestamp
    homeassistant.util.dt.set_time(datetime.datetime(2026, 6, 9, 15, 55, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=2))))
    event6 = MockEvent("sensor.automowerkv5_mower_error_message", MockState("Fault 0"))
    await manager._async_state_changed_event(event6)
    assert state.recovery_state == RecoveryState.CLEARED_BUT_UNVERIFIED
    assert state.last_real_error == "No traction"
    assert state.last_real_error_at == t2


@pytest.mark.asyncio
async def test_rehydrate_preserves_cleared_but_unverified() -> None:
    """Test state machine preserves cleared_but_unverified across simulated restart."""
    hass = MagicMock()
    
    # Setup mock HA database to show no error for automowersbv14
    def mock_get(entity_id: str) -> MockState | None:
        if entity_id == "sensor.automowersbv14_mower_error_message":
            return MockState("Fault 0")
        if entity_id == "binary_sensor.automowersbv14_mower_error":
            return MockState("off")
        return MockState("unknown")
    hass.states.get = mock_get

    manager = AutomowerSupervisorManager(hass)
    
    # Inject storage data into manager store
    t_stored = "2026-06-08T15:40:26+02:00"
    manager._storage._store.data = {
        "automowersbv14": {
            "last_real_error": "Blade disc blocked",
            "last_real_error_at": t_stored,
            "error_cleared_at": "2026-06-08T15:41:00+02:00",
            "current_error_active": False,
            "recovery_state": "cleared_but_unverified",
        }
    }
    
    await manager.async_setup()
    
    # Verify values rehydrated and did NOT clear to none/recovered
    state = manager.robots["automowersbv14"]
    assert state.recovery_state == RecoveryState.CLEARED_BUT_UNVERIFIED
    assert state.last_real_error == "Blade disc blocked"
    assert state.last_real_error_at == t_stored
    assert state.current_error_active is False


@pytest.mark.asyncio
async def test_contradictory_states() -> None:
    """Test priority evaluation when binary sensor and error message contradict."""
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    
    manager = AutomowerSupervisorManager(hass)
    await manager.async_setup()
    
    robot_id = "automowertuv4"
    state = manager.robots[robot_id]
    
    # CASE A: Binary error is 'on', message is 'Fault 0' -> active_error
    state.binary_error = "on"
    state.current_error_message = "Fault 0"
    manager._update_robot_error_state(robot_id, "2026-06-09T09:15:00")
    assert state.current_error_active is True
    assert state.recovery_state == RecoveryState.ACTIVE_ERROR
    
    # CASE B: Binary error is 'off', message is 'Wheel motor blocked' -> active_error
    state.binary_error = "off"
    state.current_error_message = "Wheel motor blocked"
    manager._update_robot_error_state(robot_id, "2026-06-09T09:15:00")
    assert state.current_error_active is True
    assert state.recovery_state == RecoveryState.ACTIVE_ERROR


@pytest.mark.asyncio
async def test_unknown_state_handling() -> None:
    """Test that unknown states clear real-time values, report in lists, and impact warning/reasons."""
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    
    manager = AutomowerSupervisorManager(hass)
    await manager.async_setup()
    
    robot_id = "automowerkv5"
    state = manager.robots[robot_id]
    sensor = AutomowerRobotSensor(robot_id, manager)
    
    # Set status to mowing
    event_status = MockEvent("sensor.automowerkv5_mower_status", MockState("Mowing"))
    await manager._async_state_changed_event(event_status)
    assert state.current_status == "Mowing"
    
    # Go to unknown
    event_unknown = MockEvent("sensor.automowerkv5_mower_status", MockState("unknown"))
    await manager._async_state_changed_event(event_unknown)
    
    # Real-time field MUST be None and list updated
    assert state.current_status is None
    assert "sensor.automowerkv5_mower_status" in state.unknown_entities
    
    # Insufficient data if fewer than 2 central entities are available
    assert sensor.native_value == "insufficient_data"
    
    # Simulate finding status and battery via state changed events
    event_status_valid = MockEvent("sensor.automowerkv5_mower_status", MockState("Mowing"))
    await manager._async_state_changed_event(event_status_valid)
    
    event_batt_valid = MockEvent("sensor.automowerkv5_mower_battery_charge", MockState("95"))
    await manager._async_state_changed_event(event_batt_valid)
    
    # Now warning because clock is missing
    assert sensor.native_value == "warning"
    
    # Set status_plain to valid so we have enough available entities when battery is unknown
    event_status_plain = MockEvent("sensor.automowerkv5_mower_status_plain", MockState("mowing"))
    await manager._async_state_changed_event(event_status_plain)
    
    # Set battery_charge to unknown
    event_batt_unknown = MockEvent("sensor.automowerkv5_mower_battery_charge", MockState("unknown"))
    await manager._async_state_changed_event(event_batt_unknown)
    assert state.current_battery is None
    assert "sensor.automowerkv5_mower_battery_charge" in state.unknown_entities
    
    # Warning because battery is unknown (and status and status_plain are available)
    assert sensor.native_value == "warning"
    # Reasons contains UNKNOWN_ENTITIES
    assert "UNKNOWN_ENTITIES" in sensor.extra_state_attributes["assessment_reasons"]


@pytest.mark.asyncio
async def test_discovery_metrics_and_uniqueness() -> None:
    """Test discovery aggregation logic and duplicate entity lists prevention."""
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    
    manager = AutomowerSupervisorManager(hass)
    await manager.async_setup()
    
    disc_sensor = AutomowerDiscoverySensor(manager)
    state = manager.robots["automowerkv5"]
    
    # Initially all expected are missing, total expected = 11 * 12 = 132
    attrs = disc_sensor.extra_state_attributes
    assert attrs["entities_expected"] == 132
    assert attrs["entities_missing"] == 132
    assert attrs["entities_found"] == 0
    assert attrs["entities_unavailable"] == 0
    assert attrs["entities_unknown"] == 0
    
    # Set status to Mowing (Found)
    event1 = MockEvent("sensor.automowerkv5_mower_status", MockState("Mowing"))
    await manager._async_state_changed_event(event1)
    
    # Set status_plain to unavailable
    event2 = MockEvent("sensor.automowerkv5_mower_status_plain", MockState("unavailable"))
    await manager._async_state_changed_event(event2)
    
    # Set clock to unknown
    event3 = MockEvent("sensor.automowerkv5_clock_time", MockState("unknown"))
    await manager._async_state_changed_event(event3)
    
    attrs_updated = disc_sensor.extra_state_attributes
    assert attrs_updated["entities_missing"] == 129
    assert attrs_updated["entities_unavailable"] == 1
    assert attrs_updated["entities_unknown"] == 1
    assert attrs_updated["entities_found"] == 1
    
    # Verify exact calculations
    # entities_found = 132 - 129 - 1 - 1 = 1
    assert attrs_updated["entities_found"] == 1
    
    # Ensure no duplicates: send unavailable state again
    await manager._async_state_changed_event(event2)
    assert len(state.unavailable_entities) == 1
    assert state.unavailable_entities.count("sensor.automowerkv5_mower_status_plain") == 1
    
    # Enforce mutual exclusivity
    # Make status_plain unknown (should move from unavailable to unknown)
    event2_unknown = MockEvent("sensor.automowerkv5_mower_status_plain", MockState("unknown"))
    await manager._async_state_changed_event(event2_unknown)
    assert "sensor.automowerkv5_mower_status_plain" not in state.unavailable_entities
    assert "sensor.automowerkv5_mower_status_plain" in state.unknown_entities


@pytest.mark.asyncio
async def test_unload_sequence_and_idempotence() -> None:
    """Test unload sequences: platform unload before manager unload, and idempotency."""
    hass = MagicMock()
    
    # Setup mock helper for async_unload_platforms to return True
    hass.config_entries = MagicMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    
    from custom_components.automower_supervisor import async_unload_entry
    
    entry = MockConfigEntry()
    manager = AutomowerSupervisorManager(hass)
    entry.runtime_data = manager
    
    # Setup track state change spy to verify unsub
    unsub_mock = MagicMock()
    manager._unsub_listener = unsub_mock
    
    # Run unload
    res = await async_unload_entry(hass, entry)
    
    assert res is True
    # Verify manager listeners and callbacks cleared
    assert manager._unsub_listener is None
    assert len(manager._callbacks) == 0
    unsub_mock.assert_called_once()
    
    # Verify idempotence (a second unload does not crash)
    await manager.async_unload()
    assert manager._unsub_listener is None


@pytest.mark.asyncio
async def test_sync_initial_states_missing_reset() -> None:
    """Test that missing entities (None state) during sync_initial_states resets values to None."""
    hass = MagicMock()
    
    # 1. Initially, entity exists and has a value
    states_db = {
        "sensor.automowerkv5_mower_battery_charge": MockState("75")
    }
    
    def mock_get(entity_id: str) -> MockState | None:
        return states_db.get(entity_id)
        
    hass.states.get = mock_get
    
    manager = AutomowerSupervisorManager(hass)
    manager.sync_initial_states()
    
    # Verify current_battery is 75
    state = manager.robots["automowerkv5"]
    assert state.current_battery == 75
    assert "sensor.automowerkv5_mower_battery_charge" not in state.missing_entities
    
    # 2. Entity is removed (states.get returns None) and sync_initial_states is run again
    states_db.clear()
    manager.sync_initial_states()
    
    # Verify current_battery is None and it is tracked in missing_entities
    assert state.current_battery is None
    assert "sensor.automowerkv5_mower_battery_charge" in state.missing_entities


@pytest.mark.asyncio
async def test_delayed_save_latest_data() -> None:
    """Test that delayed save uses the latest data from the manager at the time of execution."""
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    
    manager = AutomowerSupervisorManager(hass)
    await manager.async_setup()
    
    robot_id = "automowerkv5"
    state = manager.robots[robot_id]
    
    # Initial state
    state.last_real_error = "Blade disc blocked"
    
    captured_callback = None
    def mock_async_delay_save(callback: Callable[[], dict[str, Any]], delay: float) -> None:
        nonlocal captured_callback
        captured_callback = callback
        
    # Override store's async_delay_save to capture callback instead of executing immediately
    manager._storage._store.async_delay_save = mock_async_delay_save
    
    # Trigger change
    event = MockEvent("sensor.automowerkv5_mower_error_message", MockState("No traction"))
    await manager._async_state_changed_event(event)
    
    assert captured_callback is not None
    
    # Modify data BEFORE the callback is executed (simulating delay)
    state.last_real_error = "No traction"
    
    # Execute callback (simulating write time)
    resolved_data = captured_callback()
    
    assert resolved_data[robot_id]["last_real_error"] == "No traction"


@pytest.mark.asyncio
async def test_watchdog_scenarios() -> None:
    """Comprehensive test suite for watchdog scenarios."""
    hass = MagicMock()
    hass._mock_time_callbacks = []
    
    states_db = {}
    def mock_get(entity_id: str) -> MockState | None:
        return states_db.get(entity_id)
    hass.states.get = mock_get

    manager = AutomowerSupervisorManager(hass)
    await manager.async_setup()
    
    # 8. Watchdog timer is registered during setup with interval of 5 minutes
    assert len(hass._mock_time_callbacks) == 1
    action, interval = hass._mock_time_callbacks[0]
    assert interval == datetime.timedelta(minutes=5)
    
    robot_id = "automowerkv5"
    state = manager.robots[robot_id]
    sensor = AutomowerRobotSensor(robot_id, manager)
    disc_sensor = AutomowerDiscoverySensor(manager)
    
    now = datetime.datetime(2026, 6, 9, 12, 0, 0, tzinfo=datetime.timezone.utc)
    homeassistant.util.dt.set_time(now)
    
    # 1. Fresh heartbeat gives online = True
    states_db[state.entity_ids["clock"]] = MockState("12:00", last_updated=now - datetime.timedelta(minutes=2))
    states_db[state.entity_ids["status"]] = MockState("Mowing", last_updated=now - datetime.timedelta(minutes=3))
    states_db[state.entity_ids["status_plain"]] = MockState("mowing", last_updated=now - datetime.timedelta(minutes=3))
    states_db[state.entity_ids["battery"]] = MockState("80", last_updated=now - datetime.timedelta(minutes=3))
    states_db[state.entity_ids["error_message"]] = MockState("none", last_updated=now - datetime.timedelta(minutes=3))
    states_db[state.entity_ids["error_binary"]] = MockState("off", last_updated=now - datetime.timedelta(minutes=3))
    
    await manager._async_watchdog_check(now)
    assert state.online is True
    assert state.source_age_minutes == 2
    assert sensor.native_value == "ok"
    assert sensor.extra_state_attributes["online"] is True
    assert sensor.extra_state_attributes["source_values_stale"] is False
    
    # 2. All heartbeat-entities go to unavailable after being fresh
    for key in ["clock", "status", "status_plain", "battery", "error_message", "error_binary"]:
        states_db[state.entity_ids[key]] = MockState("unavailable", last_updated=now)
        
    # 3. After 5 minutes (still unavailable), robot is still online = True (grace period)
    now_5 = now + datetime.timedelta(minutes=5)
    await manager._async_watchdog_check(now_5)
    assert state.online is True
    assert state.source_age_minutes == 7  # 5 + 2 minutes since last seen
    assert sensor.native_value == "insufficient_data"  # all entities unavailable, but NOT critical/offline
    assert sensor.extra_state_attributes["online"] is True
    
    # 4. After 20 minutes, robot is warning with STALE_SOURCE_DATA
    now_20 = now + datetime.timedelta(minutes=20)
    await manager._async_watchdog_check(now_20)
    assert state.online is True
    assert state.source_age_minutes == 22  # 20 + 2
    assert sensor.native_value == "warning"
    assert "STALE_SOURCE_DATA" in sensor.extra_state_attributes["assessment_reasons"]
    assert sensor.extra_state_attributes["source_values_stale"] is True
    
    # 5. After 61 minutes, robot is critical with ROBOT_OFFLINE
    now_61 = now + datetime.timedelta(minutes=61)
    await manager._async_watchdog_check(now_61)
    assert state.online is False
    assert state.source_age_minutes == 63  # 61 + 2
    assert sensor.native_value == "critical"
    assert "ROBOT_OFFLINE" in sensor.extra_state_attributes["assessment_reasons"]
    assert sensor.extra_state_attributes["source_values_stale"] is True
    
    # 6. All entities unavailable without any previous heartbeat gives online = None (NO_HEARTBEAT_DATA)
    state.last_heartbeat_seen_at = None
    state.last_source_update_at = None
    await manager._async_watchdog_check(now)
    assert state.online is None
    assert state.source_age_minutes is None
    assert "NO_HEARTBEAT_DATA" in sensor.extra_state_attributes["assessment_reasons"]
    assert sensor.native_value != "critical"
    
    # 7. Clock unavailable but status fresh gives online = True
    states_db[state.entity_ids["clock"]] = MockState("unavailable", last_updated=now)
    states_db[state.entity_ids["status"]] = MockState("Mowing", last_updated=now - datetime.timedelta(minutes=5))
    states_db[state.entity_ids["status_plain"]] = MockState("mowing", last_updated=now - datetime.timedelta(minutes=5))
    states_db[state.entity_ids["battery"]] = MockState("80", last_updated=now - datetime.timedelta(minutes=5))
    states_db[state.entity_ids["error_message"]] = MockState("none", last_updated=now - datetime.timedelta(minutes=5))
    states_db[state.entity_ids["error_binary"]] = MockState("off", last_updated=now - datetime.timedelta(minutes=5))
    
    await manager._async_watchdog_check(now)
    assert state.online is True
    assert state.source_age_minutes == 5
    assert sensor.native_value == "warning"  # warning due to unavailable clock, but online is True
    
    # 8. Watchdog that detects active_error -> cleared_but_unverified schedules a persistent save
    # Setup initial active error
    state.recovery_state = RecoveryState.ACTIVE_ERROR
    state.current_error_active = True
    state.last_real_error = "Blade disc blocked"
    
    # Override store's async_delay_save to spy on it
    save_called = False
    def spy_async_delay_save(callback: Callable[[], dict[str, Any]], delay: float) -> None:
        nonlocal save_called
        save_called = True
    manager._storage.async_delay_save = spy_async_delay_save
    
    # Trigger change via states_db: error_message goes to Fault 0 (cleared but unverified)
    states_db[state.entity_ids["error_message"]] = MockState("Fault 0", last_updated=now)
    
    await manager._async_watchdog_check(now)
    assert state.recovery_state == RecoveryState.CLEARED_BUT_UNVERIFIED
    assert save_called is True
    
    # 9. Watchdog that does NOT change error status does not schedule unnecessary save
    save_called = False
    await manager._async_watchdog_check(now)
    assert save_called is False
    
    # 10. Watchdog does not modify last_real_error_at during normal runs
    state.last_real_error_at = "2026-06-09T10:00:00"
    await manager._async_watchdog_check(now)
    assert state.last_real_error_at == "2026-06-09T10:00:00"
    
    # 9 (timer unregister). Timer is unregistered at unload
    unsub_mock = MagicMock()
    manager._unsub_watchdog = unsub_mock
    await manager.async_unload()
    unsub_mock.assert_called_once()
    assert manager._unsub_watchdog is None

    # 10 (timer reload). Reload does not create duplicate timers (idempotent unload handles this)
    await manager.async_unload()
    
    # 14. Discovery totals for online/stale/offline are correct
    state1 = manager.robots["automowerkv5"]
    state1.online = True
    state1.source_age_minutes = 5
    
    state2 = manager.robots["automowertuv4"]
    state2.online = True
    state2.source_age_minutes = 20
    
    state3 = manager.robots["automowervv14mini"]
    state3.online = False
    
    attrs = disc_sensor.extra_state_attributes
    assert attrs["robots_online"] == 1
    assert attrs["robots_stale"] == 1
    assert attrs["robots_offline"] == 1
    assert attrs["robots_unknown_online_state"] == 8


@pytest.mark.asyncio
async def test_setup_optimizations() -> None:
    """Test setup optimizations to avoid duplicate state sync during setup."""
    hass = MagicMock()
    hass._mock_time_callbacks = []
    
    # 1. Setup when storage_changed = False
    hass.states.get = MagicMock(return_value=None)
    manager = AutomowerSupervisorManager(hass)
    
    sync_calls = 0
    original_sync = manager.sync_initial_states
    def spy_sync(*args, **kwargs) -> bool:
        nonlocal sync_calls
        sync_calls += 1
        return original_sync(*args, **kwargs)
    manager.sync_initial_states = spy_sync
    
    save_calls = 0
    async def spy_save(data: dict) -> None:
        nonlocal save_calls
        save_calls += 1
    manager._storage.async_save = spy_save
    
    await manager.async_setup()
    
    # Verify sync_initial_states is called exactly once during setup
    assert sync_calls == 1
    # Verify watchdog_checked_at is set
    assert manager.watchdog_checked_at is not None
    # Verify storage async_save was not called because storage_changed is False
    assert save_calls == 0
    
    # 2. Setup when storage_changed = True
    manager2 = AutomowerSupervisorManager(hass)
    manager2._storage._store.data = {
        "automowerkv5": {
            "last_real_error": "Blade disc blocked",
            "last_real_error_at": "2026-06-08T15:40:26+02:00",
            "error_cleared_at": None,
            "current_error_active": True,
            "recovery_state": "active_error",
        }
    }
    
    # HA states.get returns no error (Fault 0 / off) to trigger state transitions
    def mock_get(entity_id: str) -> Any:
        if entity_id == "sensor.automowerkv5_mower_error_message":
            return MockState("Fault 0")
        if entity_id == "binary_sensor.automowerkv5_mower_error":
            return MockState("off")
        # Provide clock and battery to calculate watchdog metrics
        if "clock" in entity_id:
            return MockState("12:00", last_updated=homeassistant.util.dt.now())
        if "battery" in entity_id:
            return MockState("90", last_updated=homeassistant.util.dt.now())
        return None
    hass.states.get = mock_get
    
    sync_calls2 = 0
    original_sync2 = manager2.sync_initial_states
    def spy_sync2(*args, **kwargs) -> bool:
        nonlocal sync_calls2
        sync_calls2 += 1
        return original_sync2(*args, **kwargs)
    manager2.sync_initial_states = spy_sync2
    
    save_calls2 = 0
    async def spy_save2(data: dict) -> None:
        nonlocal save_calls2
        save_calls2 += 1
    manager2._storage.async_save = spy_save2
    
    await manager2.async_setup()
    
    # sync_initial_states called exactly once during setup
    assert sync_calls2 == 1
    # Since storage_changed was True, async_save was called immediately
    assert save_calls2 == 1
    # watchdog metrics calculated: online should be True
    assert manager2.robots["automowerkv5"].online is True
    assert manager2.robots["automowerkv5"].source_age_minutes is not None
    
    # 3. Test periodic watchdog check still runs full sync and calls callbacks
    sync_calls_watchdog = 0
    def spy_sync_watchdog(*args, **kwargs) -> bool:
        nonlocal sync_calls_watchdog
        sync_calls_watchdog += 1
        return original_sync2(*args, **kwargs)
    manager2.sync_initial_states = spy_sync_watchdog
    
    cb_called = False
    def test_cb() -> None:
        nonlocal cb_called
        cb_called = True
    manager2.async_register_callback(test_cb)
    
    await manager2._async_watchdog_check(homeassistant.util.dt.now())
    # sync_initial_states is called again during watchdog run
    assert sync_calls_watchdog == 1
    # Callback notified
    assert cb_called is True
    
    # 4. Timer registrations
    # Check interval for manager2 timer registration (2 timers total now: one for manager, one for manager2)
    assert len(hass._mock_time_callbacks) == 2
    assert hass._mock_time_callbacks[0][1] == datetime.timedelta(minutes=5)
    assert hass._mock_time_callbacks[1][1] == datetime.timedelta(minutes=5)


@pytest.mark.asyncio
async def test_watchdog_timezone_calculations() -> None:
    """Test watchdog handles timezone difference calculations correctly."""
    hass = MagicMock()
    
    # Mocking states in HA
    states_db = {}
    def mock_get(entity_id: str) -> Any:
        return states_db.get(entity_id)
    hass.states.get = mock_get
    
    manager = AutomowerSupervisorManager(hass)
    await manager.async_setup()
    
    robot_id = "automowerkv5"
    state = manager.robots[robot_id]
    sensor = AutomowerRobotSensor(robot_id, manager)
    
    # 1. now in Europe/Stockholm (UTC+2) and last_updated in UTC with same physical time:
    # 13:00:40+02:00 vs 11:00:40+00:00 (difference should be 0 minutes)
    now = datetime.datetime(2026, 6, 9, 13, 0, 40, tzinfo=datetime.timezone(datetime.timedelta(hours=2)))
    last_updated = datetime.datetime(2026, 6, 9, 11, 0, 40, tzinfo=datetime.timezone.utc)
    
    states_db[state.entity_ids["clock"]] = MockState("11:00", last_updated=last_updated)
    states_db[state.entity_ids["status"]] = MockState("Mowing", last_updated=last_updated)
    states_db[state.entity_ids["status_plain"]] = MockState("mowing", last_updated=last_updated)
    states_db[state.entity_ids["battery"]] = MockState("80", last_updated=last_updated)
    states_db[state.entity_ids["error_message"]] = MockState("none", last_updated=last_updated)
    states_db[state.entity_ids["error_binary"]] = MockState("off", last_updated=last_updated)
    
    await manager._async_watchdog_check(now)
    
    assert state.online is True
    assert state.source_age_minutes == 0
    assert sensor.native_value == "ok"
    assert sensor.extra_state_attributes["online"] is True
    assert sensor.extra_state_attributes["source_values_stale"] is False
    
    # 2. UTC and local timezone with 5 minutes of physical difference:
    # now = 13:05:40+02:00, last_updated = 11:00:40+00:00 -> 5 minutes difference
    now_5 = datetime.datetime(2026, 6, 9, 13, 5, 40, tzinfo=datetime.timezone(datetime.timedelta(hours=2)))
    await manager._async_watchdog_check(now_5)
    assert state.online is True
    assert state.source_age_minutes == 5
    
    # 3. 20 minutes physical difference -> stale/warning
    # now = 13:20:40+02:00, last_updated = 11:00:40+00:00 -> 20 minutes difference
    now_20 = datetime.datetime(2026, 6, 9, 13, 20, 40, tzinfo=datetime.timezone(datetime.timedelta(hours=2)))
    await manager._async_watchdog_check(now_20)
    assert state.online is True
    assert state.source_age_minutes == 20
    assert sensor.native_value == "warning"
    assert sensor.extra_state_attributes["source_values_stale"] is True
    assert "STALE_SOURCE_DATA" in sensor.extra_state_attributes["assessment_reasons"]
    
    # 4. 61 minutes physical difference -> offline/critical
    # now = 14:01:40+02:00, last_updated = 11:00:40+00:00 -> 61 minutes difference
    now_61 = datetime.datetime(2026, 6, 9, 14, 1, 40, tzinfo=datetime.timezone(datetime.timedelta(hours=2)))
    await manager._async_watchdog_check(now_61)
    assert state.online is False
    assert state.source_age_minutes == 61
    assert sensor.native_value == "critical"
    assert sensor.extra_state_attributes["source_values_stale"] is True
    assert "ROBOT_OFFLINE" in sensor.extra_state_attributes["assessment_reasons"]
    
    # 5. Individual stale entities age is calculated based on timezone-aware differences:
    # Update clock to be fresh (13:01:40+02:00, which is 11:01:40+00:00, so age = 0 when now = 13:01:40+02:00)
    # But status_plain is still 11:00:40+00:00 (20 minutes older -> should be in stale_entities)
    now_stale = datetime.datetime(2026, 6, 9, 13, 20, 40, tzinfo=datetime.timezone(datetime.timedelta(hours=2)))
    states_db[state.entity_ids["clock"]] = MockState("11:20", last_updated=datetime.datetime(2026, 6, 9, 11, 20, 40, tzinfo=datetime.timezone.utc))
    states_db[state.entity_ids["status_plain"]] = MockState("mowing", last_updated=datetime.datetime(2026, 6, 9, 11, 0, 40, tzinfo=datetime.timezone.utc))
    
    await manager._async_watchdog_check(now_stale)
    assert state.source_age_minutes == 0 # latest update (clock) is fresh (age 0)
    assert state.online is True
    # status_plain has age 20 minutes (2026-06-09 11:00:40+00:00 vs now 13:20:40+02:00) -> should be stale
    assert state.entity_ids["status_plain"] in state.stale_entities
    
    # 6. Previously seen heartbeat timestamp from ISO string parsed and converted properly:
    # Clear states_db so useful_heartbeats is empty, simulating unavailable state.
    # Set state.last_heartbeat_seen_at to "2026-06-09T11:00:40+00:00"
    for key in ["clock", "status", "status_plain", "battery", "error_message", "error_binary"]:
        states_db[state.entity_ids[key]] = MockState("unavailable", last_updated=homeassistant.util.dt.now())
        
    state.last_heartbeat_seen_at = "2026-06-09T11:00:40+00:00"
    # now = 13:20:40+02:00 -> difference is 20 minutes
    now_seen = datetime.datetime(2026, 6, 9, 13, 20, 40, tzinfo=datetime.timezone(datetime.timedelta(hours=2)))
    await manager._async_watchdog_check(now_seen)
    assert state.online is True
    assert state.source_age_minutes == 20
    
    # 7. Check manager.py using regex to verify no replace(tzinfo=None) remains in the watchdog code
    import os
    manager_path = os.path.join(os.path.dirname(__file__), "../custom_components/automower_supervisor/manager.py")
    with open(manager_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "replace(tzinfo=None)" not in content


@pytest.mark.asyncio
async def test_version_0_3_2_scenarios() -> None:
    """Comprehensive tests for version 0.3.2 requirements."""
    hass = MagicMock()
    hass._mock_time_callbacks = []
    states_db = {}
    def mock_get(entity_id: str) -> MockState | None:
        return states_db.get(entity_id)
    hass.states.get = mock_get

    manager = AutomowerSupervisorManager(hass)
    await manager.async_setup()
    
    robot_id = "automowerkv5"
    state = manager.robots[robot_id]
    sensor = AutomowerRobotSensor(robot_id, manager)
    
    # Base timestamp: 2026-06-09 12:00:00 UTC (14:00:00 Stockholm, within schedule 11:00-18:00)
    base_time = datetime.datetime(2026, 6, 9, 12, 0, 0, tzinfo=datetime.timezone.utc)
    homeassistant.util.dt.set_time(base_time)
    
    # Initialize all central entities to good states
    states_db[state.entity_ids["clock"]] = MockState("12:00", last_updated=base_time)
    states_db[state.entity_ids["status"]] = MockState("Sleeping", last_updated=base_time)
    states_db[state.entity_ids["status_plain"]] = MockState("sleeping", last_updated=base_time)
    states_db[state.entity_ids["battery"]] = MockState("100", last_updated=base_time)
    states_db[state.entity_ids["distance"]] = MockState("1000", last_updated=base_time)
    states_db[state.entity_ids["statistic_hours"]] = MockState("100.0", last_updated=base_time)
    states_db[state.entity_ids["error_message"]] = MockState("none", last_updated=base_time)
    states_db[state.entity_ids["error_binary"]] = MockState("off", last_updated=base_time)
    
    manager.sync_initial_states()
    await manager._async_watchdog_check(base_time)
    assert state.online is True
    assert sensor.native_value == "ok"

    # Status priority tests (Problem 1 & 7)
    # 1. current_status = "2" and current_status_plain = "Mowing" selects "Mowing" (starts session because plain is Mowing)
    t_pri = base_time + datetime.timedelta(seconds=30)
    homeassistant.util.dt.set_time(t_pri)
    states_db[state.entity_ids["status"]] = MockState("2", last_updated=t_pri)
    states_db[state.entity_ids["status_plain"]] = MockState("Mowing", last_updated=t_pri)
    await manager._async_state_changed_event(MockEvent(state.entity_ids["status"], MockState("2", last_updated=t_pri)))
    await manager._async_state_changed_event(MockEvent(state.entity_ids["status_plain"], MockState("Mowing", last_updated=t_pri)))
    
    # Verify that session is started (meaning it selected Mowing, not 2)
    assert state.mowing_session_active is True
    assert state.pending_session_end is False
    # Verify that last_mowing_attempt_at is not updated when session starts (Problem 3)
    assert state.last_mowing_attempt_at is None

    # 2. Numeric status does not pause a session when plain status is "Mowing"
    t_pri2 = t_pri + datetime.timedelta(seconds=30)
    homeassistant.util.dt.set_time(t_pri2)
    states_db[state.entity_ids["status"]] = MockState("2", last_updated=t_pri2)
    states_db[state.entity_ids["status_plain"]] = MockState("Mowing", last_updated=t_pri2)
    await manager._async_state_changed_event(MockEvent(state.entity_ids["status"], MockState("2", last_updated=t_pri2)))
    await manager._async_state_changed_event(MockEvent(state.entity_ids["status_plain"], MockState("Mowing", last_updated=t_pri2)))
    assert state.mowing_session_active is True
    assert state.pending_session_end is False

    # 3. current_status = "7" and current_status_plain = "Fault" selects "Fault" (terminates session)
    t_pri3 = t_pri2 + datetime.timedelta(seconds=30)
    homeassistant.util.dt.set_time(t_pri3)
    states_db[state.entity_ids["status"]] = MockState("7", last_updated=t_pri3)
    states_db[state.entity_ids["status_plain"]] = MockState("Fault", last_updated=t_pri3)
    await manager._async_state_changed_event(MockEvent(state.entity_ids["status"], MockState("7", last_updated=t_pri3)))
    await manager._async_state_changed_event(MockEvent(state.entity_ids["status_plain"], MockState("Fault", last_updated=t_pri3)))
    assert state.mowing_session_active is False
    assert state.last_mowing_attempt_result == "failed_error_during_mowing"
    # Verify that last_mowing_attempt_at is updated when session ends (Problem 3)
    assert state.last_mowing_attempt_at is not None

    # 4. Watchdog prioritizes plain-status before numeric status
    t_wd_pri = t_pri3 + datetime.timedelta(seconds=30)
    homeassistant.util.dt.set_time(t_wd_pri)
    # Start session again
    states_db[state.entity_ids["status"]] = MockState("Mowing", last_updated=t_wd_pri)
    states_db[state.entity_ids["status_plain"]] = MockState("mowing", last_updated=t_wd_pri)
    await manager._async_state_changed_event(MockEvent(state.entity_ids["status"], MockState("Mowing", last_updated=t_wd_pri)))
    await manager._async_state_changed_event(MockEvent(state.entity_ids["status_plain"], MockState("mowing", last_updated=t_wd_pri)))
    assert state.mowing_session_active is True
    
    # Watchdog run with status = "7" (terminating) but status_plain = "Mowing" (active)
    t_wd_pri2 = t_wd_pri + datetime.timedelta(minutes=5)
    homeassistant.util.dt.set_time(t_wd_pri2)
    states_db[state.entity_ids["status"]] = MockState("7", last_updated=t_wd_pri2)
    states_db[state.entity_ids["status_plain"]] = MockState("mowing", last_updated=t_wd_pri2)
    states_db[state.entity_ids["clock"]] = MockState("12:06", last_updated=t_wd_pri2)
    
    await manager._async_watchdog_check(t_wd_pri2)
    assert state.mowing_session_active is True
    
    # End the session to clean up
    states_db[state.entity_ids["status"]] = MockState("Charging", last_updated=t_wd_pri2)
    states_db[state.entity_ids["status_plain"]] = MockState("charging", last_updated=t_wd_pri2)
    await manager._async_state_changed_event(MockEvent(state.entity_ids["status"], MockState("Charging", last_updated=t_wd_pri2)))
    await manager._async_state_changed_event(MockEvent(state.entity_ids["status_plain"], MockState("charging", last_updated=t_wd_pri2)))
    assert state.mowing_session_active is False
    state.last_mowing_attempt_result = None
    state.last_mowing_attempt_at = None
    state.last_mowing_ended_at = None

    async def set_status(status_val: str, t: datetime.datetime) -> None:
        states_db[state.entity_ids["status"]] = MockState(status_val, last_updated=t)
        states_db[state.entity_ids["status_plain"]] = MockState(status_val.lower(), last_updated=t)
        await manager._async_state_changed_event(MockEvent(state.entity_ids["status"], MockState(status_val, last_updated=t)))
        await manager._async_state_changed_event(MockEvent(state.entity_ids["status_plain"], MockState(status_val.lower(), last_updated=t)))

    # 1-6. Searching / Detecting status keeps session open and calculates times correctly
    t_start = base_time + datetime.timedelta(minutes=1)
    homeassistant.util.dt.set_time(t_start)
    await set_status("Mowing", t_start)
    assert state.mowing_session_active is True
    # Verify that last_mowing_attempt_at is not updated when session starts (Problem 3)
    assert state.last_mowing_attempt_at is None
    
    t_search = t_start + datetime.timedelta(minutes=2)
    homeassistant.util.dt.set_time(t_search)
    await set_status("Searching", t_search)
    assert state.mowing_session_active is True
    assert state.pending_session_end is True
    
    t_resume = t_search + datetime.timedelta(minutes=67)
    homeassistant.util.dt.set_time(t_resume)
    states_db[state.entity_ids["clock"]] = MockState("13:09", last_updated=t_resume)
    states_db[state.entity_ids["status"]] = MockState("Searching", last_updated=t_resume)
    states_db[state.entity_ids["status_plain"]] = MockState("searching", last_updated=t_resume)
    await manager._async_watchdog_check(t_resume)
    assert state.mowing_session_active is True
    assert state.last_mowing_attempt_result != "interrupted_searching"
    
    await set_status("Mowing", t_resume)
    assert state.mowing_session_active is True
    assert state.pending_session_end is False
    
    t_check = t_resume + datetime.timedelta(minutes=5)
    homeassistant.util.dt.set_time(t_check)
    await manager._async_watchdog_check(t_check)
    assert abs(state.accumulated_mowing_seconds - 420) < 5
    assert abs(state.session_elapsed_seconds - 4440) < 5

    # Detecting status continues same session
    t_detect = t_check + datetime.timedelta(minutes=1)
    homeassistant.util.dt.set_time(t_detect)
    await set_status("Detecting status", t_detect)
    assert state.mowing_session_active is True
    
    t_watchdog = t_detect + datetime.timedelta(minutes=15)
    homeassistant.util.dt.set_time(t_watchdog)
    await manager._async_watchdog_check(t_watchdog)
    assert state.mowing_session_active is True

    # Searching for charging station ends session
    t_sfcs = t_watchdog + datetime.timedelta(minutes=1)
    homeassistant.util.dt.set_time(t_sfcs)
    await set_status("Searching for charging station", t_sfcs)
    assert state.mowing_session_active is False

    # 7-10. Distance reset tracking, counts and confirmation
    t_mow2 = t_sfcs + datetime.timedelta(minutes=1)
    homeassistant.util.dt.set_time(t_mow2)
    states_db[state.entity_ids["distance"]] = MockState("0", last_updated=t_mow2)
    states_db[state.entity_ids["battery"]] = MockState("90", last_updated=t_mow2)
    await manager._async_state_changed_event(MockEvent(state.entity_ids["distance"], MockState("0", last_updated=t_mow2)))
    await manager._async_state_changed_event(MockEvent(state.entity_ids["battery"], MockState("90", last_updated=t_mow2)))
    await set_status("Mowing", t_mow2)
    
    assert state.session_accumulated_positive_distance == 0.0
    assert state.distance_reset_count == 0
    
    t_dist1 = t_mow2 + datetime.timedelta(minutes=5)
    states_db[state.entity_ids["distance"]] = MockState("40", last_updated=t_dist1)
    await manager._async_state_changed_event(MockEvent(state.entity_ids["distance"], MockState("40", last_updated=t_dist1)))
    assert state.session_accumulated_positive_distance == 40.0
    assert state.distance_reset_count == 0
    
    t_dist2 = t_dist1 + datetime.timedelta(minutes=1)
    states_db[state.entity_ids["distance"]] = MockState("0", last_updated=t_dist2)
    await manager._async_state_changed_event(MockEvent(state.entity_ids["distance"], MockState("0", last_updated=t_dist2)))
    assert state.session_accumulated_positive_distance == 40.0
    assert state.distance_reset_count == 1
    
    t_dist3 = t_dist2 + datetime.timedelta(minutes=5)
    states_db[state.entity_ids["distance"]] = MockState("8", last_updated=t_dist3)
    await manager._async_state_changed_event(MockEvent(state.entity_ids["distance"], MockState("8", last_updated=t_dist3)))
    assert state.session_accumulated_positive_distance == 48.0
    assert state.distance_reset_count == 1
    assert state.session_distance_activity_detected is True
    
    t_end2 = t_mow2 + datetime.timedelta(minutes=11)
    homeassistant.util.dt.set_time(t_end2)
    await set_status("Charging", t_end2)
    
    assert state.last_mowing_attempt_result == "confirmation_pending"
    assert state.pending_mowing_confirmation is True
    assert state.pending_confirmation_distance_activity is True
    assert sensor.extra_state_attributes["last_mowing_attempt_result"] == "confirmation_pending"
    assert "CONFIRMATION_PENDING" in sensor.extra_state_attributes["assessment_reasons"]

    # 11. Movement recovery works with resets
    state.recovery_state = RecoveryState.CLEARED_BUT_UNVERIFIED
    state.last_real_error_category = "movement"
    state.failed_recovery = False
    
    states_db[state.entity_ids["distance"]] = MockState("10", last_updated=t_end2)
    manager.sync_initial_states()
    assert state.recovery_previous_distance == 10.0
    assert state.recovery_accumulated_positive_distance == 0.0
    
    t_rec1 = t_end2 + datetime.timedelta(seconds=10)
    states_db[state.entity_ids["distance"]] = MockState("0", last_updated=t_rec1)
    await manager._async_state_changed_event(MockEvent(state.entity_ids["distance"], MockState("0", last_updated=t_rec1)))
    assert state.recovery_accumulated_positive_distance == 0.0
    assert state.recovery_state == RecoveryState.CLEARED_BUT_UNVERIFIED
    
    t_rec2 = t_rec1 + datetime.timedelta(seconds=10)
    states_db[state.entity_ids["distance"]] = MockState("1.5", last_updated=t_rec2)
    await manager._async_state_changed_event(MockEvent(state.entity_ids["distance"], MockState("1.5", last_updated=t_rec2)))
    assert state.recovery_accumulated_positive_distance == 1.5
    assert state.recovery_state == RecoveryState.RECOVERED

    # 12-15. Pending confirmation survives new session and is confirmed/failed independently
    state.pending_mowing_confirmation = True
    state.pending_confirmation_ended_at = t_end2.isoformat()
    state.pending_confirmation_mowing_seconds = 660
    state.pending_confirmation_session_elapsed_seconds = 660
    state.pending_confirmation_distance_activity = True
    state.last_mowing_attempt_result = "confirmation_pending"
    
    t_mow3 = t_end2 + datetime.timedelta(minutes=2)
    homeassistant.util.dt.set_time(t_mow3)
    await set_status("Mowing", t_mow3)
    
    assert state.mowing_session_active is True
    assert state.pending_mowing_confirmation is True
    assert state.pending_confirmation_ended_at == t_end2.isoformat()
    
    t_grace_end = t_end2 + datetime.timedelta(minutes=5)
    homeassistant.util.dt.set_time(t_grace_end)
    await manager._async_watchdog_check(t_grace_end)
    
    assert state.pending_mowing_confirmation is False
    assert state.last_mowing_attempt_result == "confirmed_mowing"
    assert state.last_confirmed_mowing_at == t_end2.isoformat()
    assert state.last_confirmed_mowing_duration_seconds == 660
    assert state.confirmed_mowing_today is True
    assert state.mowing_session_active is True
    assert state.accumulated_mowing_seconds == 180

    # Test error within 5 minutes of session ending
    t_end_a = t_grace_end + datetime.timedelta(minutes=10)
    state.pending_mowing_confirmation = True
    state.pending_confirmation_ended_at = t_end_a.isoformat()
    state.pending_confirmation_mowing_seconds = 600
    state.pending_confirmation_session_elapsed_seconds = 600
    state.last_mowing_attempt_result = "confirmation_pending"
    
    t_mow_b = t_end_a + datetime.timedelta(minutes=1)
    homeassistant.util.dt.set_time(t_mow_b)
    await set_status("Mowing", t_mow_b)
    
    t_err = t_end_a + datetime.timedelta(minutes=2)
    homeassistant.util.dt.set_time(t_err)
    states_db[state.entity_ids["error_message"]] = MockState("Blade disc blocked", last_updated=t_err)
    states_db[state.entity_ids["error_binary"]] = MockState("on", last_updated=t_err)
    await manager._async_state_changed_event(MockEvent(state.entity_ids["error_message"], MockState("Blade disc blocked", last_updated=t_err)))
    await manager._async_state_changed_event(MockEvent(state.entity_ids["error_binary"], MockState("on", last_updated=t_err)))
    
    # Active session B should capture the error too (Problem 5)
    assert state.session_binary_error_detected is True
    assert state.session_error_detected is True
    
    assert state.pending_mowing_confirmation is False
    assert state.last_mowing_attempt_result == "failed_error_after_mowing"
    assert state.failed_recovery is True

    # 21-22. Unknown status and explicit terminating
    states_db[state.entity_ids["error_message"]] = MockState("none", last_updated=t_err)
    states_db[state.entity_ids["error_binary"]] = MockState("off", last_updated=t_err)
    state.recovery_state = RecoveryState.NONE
    state.current_error_active = False
    state.failed_recovery = False
    state.binary_error = "off"
    state.current_error_message = "none"
    
    t_mow4 = t_err + datetime.timedelta(minutes=5)
    homeassistant.util.dt.set_time(t_mow4)
    await set_status("Mowing", t_mow4)
    assert state.mowing_session_active is True
    
    t_unknown = t_mow4 + datetime.timedelta(minutes=2)
    homeassistant.util.dt.set_time(t_unknown)
    await set_status("Going somewhere unknown", t_unknown)
    
    assert state.mowing_session_active is True
    assert state.pending_session_end is True
    assert state.interruption_status == "Going somewhere unknown"
    assert "UNKNOWN_SESSION_STATUS" in sensor.extra_state_attributes["assessment_reasons"]

    t_term = t_unknown + datetime.timedelta(minutes=2)
    homeassistant.util.dt.set_time(t_term)
    await set_status("Charging", t_term)
    assert state.mowing_session_active is False

    # 23-24. Offline over 60 minutes ends session as session_lost_offline
    t_mow5 = t_term + datetime.timedelta(minutes=2)
    homeassistant.util.dt.set_time(t_mow5)
    await set_status("Mowing", t_mow5)
    assert state.mowing_session_active is True
    
    t_offline = t_mow5 + datetime.timedelta(minutes=61)
    homeassistant.util.dt.set_time(t_offline)
    for key in ["clock", "status", "status_plain", "battery", "error_message", "error_binary"]:
        states_db[state.entity_ids[key]] = MockState("unavailable", last_updated=t_offline)
        
    await manager._async_watchdog_check(t_offline)
    assert state.online is False
    assert state.mowing_session_active is False
    assert state.last_mowing_attempt_result == "session_lost_offline"
    assert "MOWING_SESSION_LOST_OFFLINE" in sensor.extra_state_attributes["assessment_reasons"]

    # 16-18. Startup loading of pending confirmations
    manager_restart1 = AutomowerSupervisorManager(hass)
    t_restart = t_offline + datetime.timedelta(minutes=10)
    homeassistant.util.dt.set_time(t_restart)
    
    def mock_get_restart1(entity_id: str) -> Any:
        if "clock" in entity_id:
            return MockState("12:00", last_updated=t_restart)
        if "battery" in entity_id:
            return MockState("100", last_updated=t_restart)
        if "status" in entity_id:
            return MockState("Sleeping", last_updated=t_restart)
        return MockState("none", last_updated=t_restart)
    hass.states.get = mock_get_restart1
    
    t_ended = t_restart - datetime.timedelta(minutes=6)
    manager_restart1._storage._store.data = {
        "automowerkv5": {
            "pending_mowing_confirmation": True,
            "pending_confirmation_ended_at": t_ended.isoformat(),
            "pending_confirmation_mowing_seconds": 600,
            "pending_confirmation_session_elapsed_seconds": 600,
            "recovery_state": "none",
            "daily_date": "2026-06-09"
        }
    }
    
    await manager_restart1.async_setup()
    state_restart1 = manager_restart1.robots[robot_id]
    assert state_restart1.pending_mowing_confirmation is False
    assert state_restart1.last_mowing_attempt_result == "confirmed_mowing"
    assert state_restart1.confirmed_mowing_today is True
    
    manager_restart2 = AutomowerSupervisorManager(hass)
    def mock_get_restart2(entity_id: str) -> Any:
        if "error_message" in entity_id:
            return MockState("Blade disc blocked", last_updated=t_restart)
        if "error_binary" in entity_id:
            return MockState("on", last_updated=t_restart)
        return MockState("Sleeping", last_updated=t_restart)
    hass.states.get = mock_get_restart2
    
    manager_restart2._storage._store.data = {
        "automowerkv5": {
            "pending_mowing_confirmation": True,
            "pending_confirmation_ended_at": t_ended.isoformat(),
            "pending_confirmation_mowing_seconds": 600,
            "pending_confirmation_session_elapsed_seconds": 600,
            "recovery_state": "cleared_but_unverified",
            "daily_date": "2026-06-09"
        }
    }
    
    await manager_restart2.async_setup()
    state_restart2 = manager_restart2.robots[robot_id]
    assert state_restart2.pending_mowing_confirmation is False
    assert state_restart2.last_mowing_attempt_result == "failed_error_after_mowing"
    assert state_restart2.failed_recovery is True

    # 15. Startup with active pending confirmation AND robot already mowing (Problem 2, 4, 6)
    manager_restart3 = AutomowerSupervisorManager(hass)
    t_restart3 = t_offline + datetime.timedelta(minutes=20)
    homeassistant.util.dt.set_time(t_restart3)
    
    def mock_get_restart3(entity_id: str) -> Any:
        if "clock" in entity_id:
            return MockState("12:00", last_updated=t_restart3)
        if "battery" in entity_id:
            return MockState("100", last_updated=t_restart3)
        if "status" in entity_id:
            return MockState("Mowing", last_updated=t_restart3)
        if "status_plain" in entity_id:
            return MockState("mowing", last_updated=t_restart3)
        return MockState("none", last_updated=t_restart3)
    hass.states.get = mock_get_restart3
    
    t_ended3 = t_restart3 - datetime.timedelta(minutes=2) # Only 2 minutes old -> not expired
    manager_restart3._storage._store.data = {
        "automowerkv5": {
            "pending_mowing_confirmation": True,
            "pending_confirmation_ended_at": t_ended3.isoformat(),
            "pending_confirmation_mowing_seconds": 600,
            "pending_confirmation_session_elapsed_seconds": 600,
            "pending_confirmation_distance_activity": True,
            "recovery_state": "none",
            "daily_date": "2026-06-09"
        }
    }
    
    await manager_restart3.async_setup()
    state_restart3 = manager_restart3.robots[robot_id]
    
    # Coexistence check
    assert state_restart3.mowing_session_active is True
    assert state_restart3.pending_mowing_confirmation is True
    
    # Verify metadata is preserved
    assert state_restart3.pending_confirmation_ended_at == t_ended3.isoformat()
    assert state_restart3.pending_confirmation_mowing_seconds == 600
    assert state_restart3.last_mowing_attempt_at is None
    
    # Confirm A after 3 minutes (grace period finishes)
    t_confirm3 = t_ended3 + datetime.timedelta(minutes=5)
    homeassistant.util.dt.set_time(t_confirm3)
    
    states_db[state_restart3.entity_ids["clock"]] = MockState("12:05", last_updated=t_confirm3)
    states_db[state_restart3.entity_ids["status"]] = MockState("Mowing", last_updated=t_confirm3)
    states_db[state_restart3.entity_ids["status_plain"]] = MockState("mowing", last_updated=t_confirm3)
    
    await manager_restart3._async_watchdog_check(t_confirm3)
    
    assert state_restart3.pending_mowing_confirmation is False
    assert state_restart3.last_mowing_attempt_result == "confirmed_mowing"
    assert state_restart3.last_confirmed_mowing_at == t_ended3.isoformat()
    
    # B's active fields remain untouched
    assert state_restart3.mowing_session_active is True
    assert state_restart3.session_started_source == "startup_observation"
    assert state_restart3.session_started_at == homeassistant.util.dt.as_utc(t_restart3).isoformat()

    # 16. Startup with expired pending candidate AND robot already mowing
    manager_restart4 = AutomowerSupervisorManager(hass)
    t_restart4 = t_offline + datetime.timedelta(minutes=30)
    homeassistant.util.dt.set_time(t_restart4)
    
    def mock_get_restart4(entity_id: str) -> Any:
        if "clock" in entity_id:
            return MockState("12:00", last_updated=t_restart4)
        if "battery" in entity_id:
            return MockState("100", last_updated=t_restart4)
        if "status" in entity_id:
            return MockState("Mowing", last_updated=t_restart4)
        if "status_plain" in entity_id:
            return MockState("mowing", last_updated=t_restart4)
        return MockState("none", last_updated=t_restart4)
    hass.states.get = mock_get_restart4
    
    t_ended4 = t_restart4 - datetime.timedelta(minutes=6) # expired
    manager_restart4._storage._store.data = {
        "automowerkv5": {
            "pending_mowing_confirmation": True,
            "pending_confirmation_ended_at": t_ended4.isoformat(),
            "pending_confirmation_mowing_seconds": 600,
            "pending_confirmation_session_elapsed_seconds": 600,
            "pending_confirmation_distance_activity": True,
            "recovery_state": "none",
            "daily_date": "2026-06-09"
        }
    }
    
    await manager_restart4.async_setup()
    state_restart4 = manager_restart4.robots[robot_id]
    
    # Expired pending candidate should be confirmed immediately at startup
    assert state_restart4.pending_mowing_confirmation is False
    assert state_restart4.last_mowing_attempt_result == "confirmed_mowing"
    assert state_restart4.last_confirmed_mowing_at == t_ended4.isoformat()
    
    # B is started as a new active session
    assert state_restart4.mowing_session_active is True




