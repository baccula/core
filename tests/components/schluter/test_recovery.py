"""Test recovery through the real API client and Home Assistant scheduler."""

from datetime import timedelta
import re

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

BASE_URL = "https://ditra-heat-e-wifi.schluter.com"
THERMOSTAT_RESPONSE = {
    "Groups": [
        {
            "Thermostats": [
                {
                    "SerialNumber": "TEST123",
                    "Room": "Bathroom",
                    "Temperature": 2250,
                    "SetPointTemp": 2400,
                    "MinTemp": 500,
                    "MaxTemp": 4000,
                    "Online": True,
                    "Heating": True,
                }
            ]
        }
    ]
}


@pytest.mark.parametrize(
    "read_statuses",
    [
        pytest.param([200, 503, 401, 200], id="outage-then-expired-session"),
        pytest.param([200, 401, 401, 200], id="renewed-session-rejected"),
    ],
)
async def test_network_and_session_recovery(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
    read_statuses: list[int],
) -> None:
    """Polling continues after an outage or rejection of a freshly renewed session."""
    statuses = iter(read_statuses)

    async def respond(method: str, url: str, body: dict) -> AiohttpClientMockResponse:
        return AiohttpClientMockResponse(
            method, url, status=next(statuses), json=THERMOSTAT_RESPONSE
        )

    aioclient_mock.post(
        BASE_URL + "/api/authenticate/user",
        json={"ErrorCode": 0, "SessionId": "session"},
    )
    aioclient_mock.get(
        re.compile(re.escape(BASE_URL + "/api/thermostats")), side_effect=respond
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("climate.bathroom").state == "heat"

    freezer.tick(timedelta(seconds=70))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get("climate.bathroom").state == "unavailable"
    assert not hass.config_entries.flow.async_progress()

    freezer.tick(timedelta(seconds=70))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get("climate.bathroom").state == "heat"
    assert len(hass.config_entries.async_entries("schluter")) == 1
    assert aioclient_mock.call_count == 7


async def test_startup_repeated_session_rejection_recovers(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Repeated 401s after successful logins keep setup retrying until reads work."""
    statuses = iter([401, 401, 401, 401, 200])

    async def respond(method: str, url: str, body: dict) -> AiohttpClientMockResponse:
        return AiohttpClientMockResponse(
            method, url, status=next(statuses), json=THERMOSTAT_RESPONSE
        )

    aioclient_mock.post(
        BASE_URL + "/api/authenticate/user",
        json={"ErrorCode": 0, "SessionId": "session"},
    )
    aioclient_mock.get(
        re.compile(re.escape(BASE_URL + "/api/thermostats")), side_effect=respond
    )
    config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert not hass.config_entries.flow.async_progress()
    assert aioclient_mock.call_count == 4

    freezer.tick(timedelta(minutes=5))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert not hass.config_entries.flow.async_progress()
    assert aioclient_mock.call_count == 8

    freezer.tick(timedelta(minutes=5))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("climate.bathroom").state == "heat"
    assert not hass.config_entries.flow.async_progress()
    assert len(hass.config_entries.async_entries("schluter")) == 1
    assert aioclient_mock.call_count == 10
