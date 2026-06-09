"""Tests for the Automower Supervisor custom integration."""

from __future__ import annotations

import datetime
import sys
from types import ModuleType
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
    def now(self) -> datetime.datetime:
        # Fixed timezone-aware datetime: UTC+2
        return datetime.datetime(2026, 6, 9, 9, 15, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=2)))
homeassistant.util.dt = MockDt()

# ==========================================
# IMPORTING THE INTEGRATION MODULES
# ==========================================
from custom_components.automower_supervisor.const import DOMAIN, ROBOTS
from custom_components.automower_supervisor.models import RobotState, RecoveryState
from custom_components.automower_supervisor.manager import AutomowerSupervisorManager
from custom_components.automower_supervisor.sensor import AutomowerRobotSensor, AutomowerDiscoverySensor
from custom_components.automower_supervisor.config_flow import AutomowerSupervisorConfigFlow

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
    
    unsub()
    
    # Check unload
    await manager.async_unload()
    assert manager._unsub_listener is None


@pytest.mark.asyncio
async def test_error_state_transitions() -> None:
    """Test the core error state machine logic."""
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    
    manager = AutomowerSupervisorManager(hass)
    await manager.async_setup()
    
    robot_id = "automowerkv5"
    state = manager.robots[robot_id]
    
    # Assert initial state (no errors)
    assert state.recovery_state == RecoveryState.NONE
    assert state.current_error_active is False
    
    # 1. Simulate finding an active error message
    event_error = MockEvent(
        entity_id="sensor.automowerkv5_mower_error_message",
        new_state=MockState("Blade disc blocked")
    )
    await manager._async_state_changed_event(event_error)
    
    assert state.current_error_active is True
    assert state.recovery_state == RecoveryState.ACTIVE_ERROR
    assert state.last_real_error == "Blade disc blocked"
    assert state.last_real_error_at is not None
    assert state.error_cleared_at is None
    
    # 2. Simulate error clearing (goes to Fault 0)
    event_clear = MockEvent(
        entity_id="sensor.automowerkv5_mower_error_message",
        new_state=MockState("Fault 0")
    )
    await manager._async_state_changed_event(event_clear)
    
    # The fault MUST survive and transition to cleared_but_unverified
    assert state.current_error_active is False
    assert state.recovery_state == RecoveryState.CLEARED_BUT_UNVERIFIED
    assert state.last_real_error == "Blade disc blocked"
    assert state.error_cleared_at is not None
    
    # 3. Simulate binary error goes to on (while error message is Fault 0)
    event_binary_on = MockEvent(
        entity_id="binary_sensor.automowerkv5_mower_error",
        new_state=MockState("on")
    )
    await manager._async_state_changed_event(event_binary_on)
    
    assert state.current_error_active is True
    assert state.recovery_state == RecoveryState.ACTIVE_ERROR
    assert state.last_real_error == "Blade disc blocked"  # preserves message
    
    # 4. Simulate binary error goes to off (message still Fault 0)
    event_binary_off = MockEvent(
        entity_id="binary_sensor.automowerkv5_mower_error",
        new_state=MockState("off")
    )
    await manager._async_state_changed_event(event_binary_off)
    
    assert state.current_error_active is False
    assert state.recovery_state == RecoveryState.CLEARED_BUT_UNVERIFIED


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
async def test_rehydrate_from_storage() -> None:
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
    manager._storage._store.data = {
        "automowersbv14": {
            "last_real_error": "Blade disc blocked",
            "last_real_error_at": "2026-06-08T15:40:26+02:00",
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
    assert state.current_error_active is False


@pytest.mark.asyncio
async def test_sensor_assessment_states() -> None:
    """Test that the RobotSensor returns the correct states."""
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    
    manager = AutomowerSupervisorManager(hass)
    await manager.async_setup()
    
    sensor = AutomowerRobotSensor("automowerkv5", manager)
    state_data = manager.robots["automowerkv5"]
    
    # 1. Insufficient data: initially no entities found
    assert sensor.native_value == "insufficient_data"
    assert "INSUFFICIENT_DATA" in sensor.extra_state_attributes["assessment_reasons"]
    
    # Simulate finding status and battery (2 central entities)
    state_data.missing_entities.remove("sensor.automowerkv5_mower_status")
    state_data.missing_entities.remove("sensor.automowerkv5_mower_battery_charge")
    assert sensor.native_value == "warning"  # warning because some central ones still missing
    assert "MISSING_ENTITIES" in sensor.extra_state_attributes["assessment_reasons"]
    
    # Simulate finding all central entities
    for key in ["status_plain", "error_message", "error_binary", "clock"]:
        state_data.missing_entities.remove(state_data.entity_ids[key])
    assert sensor.native_value == "ok"
    assert len(sensor.extra_state_attributes["assessment_reasons"]) == 0
    
    # Simulate an active error message
    state_data.current_error_message = "Blade disc blocked"
    state_data.recovery_state = RecoveryState.ACTIVE_ERROR
    state_data.current_error_active = True
    assert sensor.native_value == "critical"
    assert "ACTIVE_ERROR_MESSAGE" in sensor.extra_state_attributes["assessment_reasons"]


@pytest.mark.asyncio
async def test_discovery_sensor_metrics() -> None:
    """Test overall discovery aggregation sensor."""
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    
    manager = AutomowerSupervisorManager(hass)
    await manager.async_setup()
    
    disc_sensor = AutomowerDiscoverySensor(manager)
    
    # Initially all entities are missing, so found robots = 0
    assert disc_sensor.native_value == 0
    
    # Mark at least one entity found for a robot
    state_kv5 = manager.robots["automowerkv5"]
    state_kv5.missing_entities.remove("sensor.automowerkv5_mower_status")
    
    # Found robots should be 1
    assert disc_sensor.native_value == 1
    
    # Check attributes structure
    attrs = disc_sensor.extra_state_attributes
    assert attrs["robots_configured"] == 11
    assert attrs["robots_found"] == 1
    assert "automowerkv5" in attrs["robots"]
    assert "status" in attrs["robots"]["automowerkv5"]["found"]
    assert "status_plain" in attrs["robots"]["automowerkv5"]["missing"]
