"""Test recovery through the real API client and Home Assistant scheduler."""

from datetime import timedelta
import re

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util


async def test_network_and_session_recovery(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A server outage followed by an expired session recovers without a restart."""
    base = "https://ditra-heat-e-wifi.schluter.com"
    data = {
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
    statuses = iter([200, 503, 401, 200])

    async def respond(method: str, url: str, body: dict) -> AiohttpClientMockResponse:
        return AiohttpClientMockResponse(method, url, status=next(statuses), json=data)

    aioclient_mock.post(
        base + "/api/authenticate/user", json={"ErrorCode": 0, "SessionId": "session"}
    )
    aioclient_mock.get(
        re.compile(re.escape(base + "/api/thermostats")), side_effect=respond
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("climate.bathroom").state == "heat"

    freezer.tick(timedelta(seconds=70))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get("climate.bathroom").state == "unavailable"

    freezer.tick(timedelta(seconds=70))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get("climate.bathroom").state == "heat"
    assert len(hass.config_entries.async_entries("schluter")) == 1
    assert aioclient_mock.call_count == 7
