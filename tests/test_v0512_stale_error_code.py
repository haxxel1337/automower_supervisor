from __future__ import annotations

import datetime
from unittest.mock import MagicMock

import pytest

import test_integration  # noqa: F401  # installs the Home Assistant test stubs

from custom_components.automower_supervisor import compat_0512
from custom_components.automower_supervisor.manager import AutomowerSupervisorManager
from custom_components.automower_supervisor.models import RecoveryState

compat_0512.install()


def _manager() -> AutomowerSupervisorManager:
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    hass.async_create_task = MagicMock()
    return AutomowerSupervisorManager(hass)


@pytest.mark.asyncio
async def test_v0512_error_code_entity_is_listened_to_without_discovery_counting() -> None:
    manager = _manager()
    state = manager.robots["automowertrv4"]

    assert "error_code" not in state.entity_ids
    assert manager._entity_lookup["sensor.automowertrv4_mower_error_code"] == (
        "automowertrv4",
        "error_code",
    )


@pytest.mark.asyncio
async def test_v0512_error_code_zero_overrides_stale_error_message() -> None:
    manager = _manager()
    state = manager.robots["automowertrv4"]

    state.current_error_message = "Battery empty"
    state.current_error_code = "0"
    state.binary_error = "off"
    state.current_error_active = True
    state.recovery_state = RecoveryState.ACTIVE_ERROR

    changed = manager._update_robot_error_state(
        "automowertrv4",
        "2026-07-10T07:58:00+02:00",
    )

    assert changed is True
    assert state.current_error_message == "Fault 0"
    assert state.current_error_active is False
    assert state.recovery_state == RecoveryState.CLEARED_BUT_UNVERIFIED
    assert state.error_cleared_at == "2026-07-10T07:58:00+02:00"


@pytest.mark.asyncio
async def test_v0512_stale_error_code_clear_eligibility() -> None:
    manager = _manager()
    state = manager.robots["automowertrv4"]

    state.online = True
    state.source_age_minutes = 0
    state.mower_data_stale = False
    state.current_status_plain = "Sleeping"
    state.current_battery = 100
    state.current_error_message = "Battery empty"
    state.current_error_code = "501"
    state.binary_error = "off"
    state.current_error_active = True
    state.last_real_error = "Battery empty"
    state.last_real_error_at = "2026-07-10T07:50:00+02:00"
    state.recovery_state = RecoveryState.ACTIVE_ERROR

    now = datetime.datetime(
        2026,
        7,
        10,
        7,
        58,
        tzinfo=datetime.timezone(datetime.timedelta(hours=2)),
    )

    assert manager._stale_error_code_clear_eligible(state, now) is True

    state.stale_error_fix_incident_at = state.last_real_error_at
    assert manager._stale_error_code_clear_eligible(state, now) is False


@pytest.mark.asyncio
async def test_v0512_robonect_buttons_include_reboot() -> None:
    buttons = AutomowerSupervisorManager._robonect_button_ids("automowertrv4")

    assert buttons["reboot"] == "button.automowertrv4_reboot"
