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
        self.last_updated = last_updated or datetime.datetime.now()

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
    # Initialize mock list
    hass._mock_time_callbacks = []
    
    # Setup state dictionary for mocking states.get
    states_db = {}
    def mock_get(entity_id: str) -> MockState | None:
        return states_db.get(entity_id)
    hass.states.get = mock_get

    # Create manager
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
    
    # Let's set some times
    now = datetime.datetime(2026, 6, 9, 12, 0, 0, tzinfo=datetime.timezone.utc)
    homeassistant.util.dt.set_time(now)
    
    # 1. Fresh clock/status gives online = True
    states_db[state.entity_ids["clock"]] = MockState("12:00", last_updated=now - datetime.timedelta(minutes=2))
    states_db[state.entity_ids["status"]] = MockState("Mowing", last_updated=now - datetime.timedelta(minutes=3))
    states_db[state.entity_ids["status_plain"]] = MockState("mowing", last_updated=now - datetime.timedelta(minutes=3))
    states_db[state.entity_ids["battery"]] = MockState("80", last_updated=now - datetime.timedelta(minutes=3))
    states_db[state.entity_ids["error_message"]] = MockState("none", last_updated=now - datetime.timedelta(minutes=3))
    states_db[state.entity_ids["error_binary"]] = MockState("off", last_updated=now - datetime.timedelta(minutes=3))
    
    # Trigger watchdog check
    await manager._async_watchdog_check(now)
    
    assert state.online is True
    assert state.source_age_minutes == 2  # closest to now is clock at 2 mins ago
    assert sensor.native_value == "ok"
    assert sensor.extra_state_attributes["online"] is True
    assert sensor.extra_state_attributes["source_values_stale"] is False
    assert len(state.stale_entities) == 0

    # 2. Clock is unavailable but another heartbeat-entity is fresh: still online
    states_db[state.entity_ids["clock"]] = MockState("unavailable", last_updated=now)
    states_db[state.entity_ids["status"]] = MockState("Mowing", last_updated=now - datetime.timedelta(minutes=5))
    states_db[state.entity_ids["status_plain"]] = MockState("mowing", last_updated=now - datetime.timedelta(minutes=5))
    states_db[state.entity_ids["battery"]] = MockState("80", last_updated=now - datetime.timedelta(minutes=5))
    states_db[state.entity_ids["error_message"]] = MockState("none", last_updated=now - datetime.timedelta(minutes=5))
    states_db[state.entity_ids["error_binary"]] = MockState("off", last_updated=now - datetime.timedelta(minutes=5))
    
    await manager._async_watchdog_check(now)
    assert state.online is True
    assert state.source_age_minutes == 5
    assert sensor.native_value == "warning"  # warning because clock is unavailable

    # 3. All heartbeat-entities older than 15 minutes gives warning and STALE_SOURCE_DATA
    states_db[state.entity_ids["clock"]] = MockState("11:40", last_updated=now - datetime.timedelta(minutes=20))
    states_db[state.entity_ids["status"]] = MockState("Mowing", last_updated=now - datetime.timedelta(minutes=25))
    states_db[state.entity_ids["status_plain"]] = MockState("mowing", last_updated=now - datetime.timedelta(minutes=25))
    states_db[state.entity_ids["battery"]] = MockState("80", last_updated=now - datetime.timedelta(minutes=25))
    states_db[state.entity_ids["error_message"]] = MockState("none", last_updated=now - datetime.timedelta(minutes=25))
    states_db[state.entity_ids["error_binary"]] = MockState("off", last_updated=now - datetime.timedelta(minutes=25))
    
    await manager._async_watchdog_check(now)
    assert state.online is True
    assert state.source_age_minutes == 20
    assert sensor.native_value == "warning"
    assert "STALE_SOURCE_DATA" in sensor.extra_state_attributes["assessment_reasons"]
    # 7. Old values get source_values_stale: True
    assert sensor.extra_state_attributes["source_values_stale"] is True

    # 4. All heartbeat-entities older than 60 minutes gives critical and ROBOT_OFFLINE
    states_db[state.entity_ids["clock"]] = MockState("10:50", last_updated=now - datetime.timedelta(minutes=70))
    states_db[state.entity_ids["status"]] = MockState("Mowing", last_updated=now - datetime.timedelta(minutes=75))
    states_db[state.entity_ids["status_plain"]] = MockState("mowing", last_updated=now - datetime.timedelta(minutes=75))
    states_db[state.entity_ids["battery"]] = MockState("80", last_updated=now - datetime.timedelta(minutes=75))
    states_db[state.entity_ids["error_message"]] = MockState("none", last_updated=now - datetime.timedelta(minutes=75))
    states_db[state.entity_ids["error_binary"]] = MockState("off", last_updated=now - datetime.timedelta(minutes=75))
    
    await manager._async_watchdog_check(now)
    assert state.online is False
    assert state.source_age_minutes == 70
    assert sensor.native_value == "critical"
    assert "ROBOT_OFFLINE" in sensor.extra_state_attributes["assessment_reasons"]
    assert sensor.extra_state_attributes["source_values_stale"] is True

    # 5. Active error is still critical regardless of heartbeat (even if fresh)
    states_db[state.entity_ids["clock"]] = MockState("12:00", last_updated=now - datetime.timedelta(minutes=2))
    states_db[state.entity_ids["status"]] = MockState("Mowing", last_updated=now - datetime.timedelta(minutes=2))
    states_db[state.entity_ids["status_plain"]] = MockState("mowing", last_updated=now - datetime.timedelta(minutes=2))
    states_db[state.entity_ids["battery"]] = MockState("80", last_updated=now - datetime.timedelta(minutes=2))
    states_db[state.entity_ids["error_binary"]] = MockState("off", last_updated=now - datetime.timedelta(minutes=2))
    states_db[state.entity_ids["error_message"]] = MockState("Blade disc blocked", last_updated=now - datetime.timedelta(minutes=2))
    
    await manager._async_watchdog_check(now)
    assert state.online is True
    assert state.current_error_active is True
    assert sensor.native_value == "critical"
    assert "ACTIVE_ERROR_MESSAGE" in sensor.extra_state_attributes["assessment_reasons"]

    # 6. cleared_but_unverified is still critical regardless of heartbeat
    states_db[state.entity_ids["error_message"]] = MockState("Fault 0", last_updated=now - datetime.timedelta(minutes=2))
    
    await manager._async_watchdog_check(now)
    assert state.recovery_state == RecoveryState.CLEARED_BUT_UNVERIFIED
    assert sensor.native_value == "critical"
    assert "CLEARED_BUT_UNVERIFIED" in sensor.extra_state_attributes["assessment_reasons"]

    # 9. Timer is unregistered at unload
    unsub_mock = MagicMock()
    manager._unsub_watchdog = unsub_mock
    await manager.async_unload()
    unsub_mock.assert_called_once()
    assert manager._unsub_watchdog is None

    # 10. Reload does not create duplicate timers (idempotent unload handles this)
    await manager.async_unload()
    
    # 11. Missing entities do not crash watchdog
    states_db.clear()
    await manager._async_watchdog_check(now)
    assert state.online is None
    
    # 12. last_real_error and its timestamp are not modified by watchdog checks
    state.last_real_error = "Blade disc blocked"
    state.last_real_error_at = "2026-06-09T10:00:00"
    await manager._async_watchdog_check(now)
    assert state.last_real_error == "Blade disc blocked"
    assert state.last_real_error_at == "2026-06-09T10:00:00"

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


