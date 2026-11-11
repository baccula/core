"""Test observable climate behavior and scheduled recovery without restarting."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed
from schluter_wifi import (
    AuthenticationError,
    CommandError,
    CommunicationError,
    RateLimitError,
)

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

from .conftest import THERMOSTAT


@pytest.mark.usefixtures("setup_integration")
async def test_state_and_commands(hass: HomeAssistant, mock_client: MagicMock) -> None:
    """Match the legacy temperature, limits, heat mode, and permanent setpoint."""
    state = hass.states.get("climate.bathroom")
    assert state.state == "heat"
    assert state.attributes["current_temperature"] == 22.5
    assert state.attributes["temperature"] == 24
    assert state.attributes["hvac_action"] == "heating"
    assert state.attributes["min_temp"] == 5
    assert state.attributes["max_temp"] == 40
    assert state.attributes["hvac_modes"] == ["heat"]
    mock_client.async_get_thermostats.return_value = {
        "TEST123": replace(THERMOSTAT, target_temperature=25, heating=False)
    }
    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": "climate.bathroom", "temperature": 25},
        blocking=True,
    )
    mock_client.async_set_temperature.assert_awaited_once_with("TEST123", 25)
    state = hass.states.get("climate.bathroom")
    assert state.attributes["temperature"] == 25
    assert state.attributes["hvac_action"] == "idle"
    await hass.services.async_call(
        "climate",
        "set_hvac_mode",
        {"entity_id": "climate.bathroom", "hvac_mode": "heat"},
        blocking=True,
    )


@pytest.mark.usefixtures("setup_integration")
@pytest.mark.parametrize(
    "error", [CommunicationError("Network offline"), RateLimitError(60)]
)
async def test_scheduled_recovery(
    hass: HomeAssistant,
    mock_client: MagicMock,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
) -> None:
    """Several failed scheduled polls must not stop the next successful poll."""
    mock_client.async_get_thermostats.side_effect = error
    for _ in range(3):
        freezer.tick(timedelta(seconds=70))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert hass.states.get("climate.bathroom").state == "unavailable"
    assert caplog.text.count("Error fetching Schluter data") == 1
    mock_client.async_get_thermostats.side_effect = None
    freezer.tick(timedelta(seconds=70))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get("climate.bathroom").state == "heat"
    assert mock_client.async_get_thermostats.await_count == 5


@pytest.mark.usefixtures("setup_integration")
@pytest.mark.parametrize("data", [{}, {"TEST123": replace(THERMOSTAT, online=False)}])
async def test_missing_or_offline_recovers(
    hass: HomeAssistant,
    mock_client: MagicMock,
    freezer: FrozenDateTimeFactory,
    data: dict,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Missing or offline devices recover with the same entity ID."""
    mock_client.async_get_thermostats.return_value = data
    for _ in range(2):
        freezer.tick(timedelta(seconds=70))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert hass.states.get("climate.bathroom").state == "unavailable"
    assert caplog.text.count("is offline or missing") == 1
    mock_client.async_get_thermostats.return_value = {"TEST123": THERMOSTAT}
    freezer.tick(timedelta(seconds=70))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get("climate.bathroom").state == "heat"
    assert len(hass.states.async_entity_ids("climate")) == 1


@pytest.mark.usefixtures("setup_integration")
@pytest.mark.parametrize(
    "error", [CommandError(), CommunicationError(), AuthenticationError()]
)
async def test_command_failure(
    hass: HomeAssistant, mock_client: MagicMock, error: Exception
) -> None:
    """Do not claim an unconfirmed command succeeded or change the displayed target."""
    mock_client.async_set_temperature.side_effect = error
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": "climate.bathroom", "temperature": 25},
            blocking=True,
        )
    assert hass.states.get("climate.bathroom").attributes["temperature"] == 24


@pytest.mark.usefixtures("mock_client")
async def test_fahrenheit(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    """Home Assistant converts US display and command temperatures exactly once."""
    hass.config.units = US_CUSTOMARY_SYSTEM
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get("climate.bathroom")
    assert state.attributes["temperature"] == 75
    assert state.attributes["min_temp"] == 41
    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": "climate.bathroom", "temperature": 77},
        blocking=True,
    )
    mock_client.async_set_temperature.assert_awaited_once_with("TEST123", 25)


async def test_initially_offline(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Log a device that is offline before its first entity update."""
    mock_client.async_get_thermostats.return_value = {
        "TEST123": replace(THERMOSTAT, online=False)
    }
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("climate.bathroom").state == "unavailable"
    assert caplog.text.count("is offline or missing") == 1
