"""Fixtures for Schluter integration tests."""

from collections.abc import Generator
from unittest.mock import MagicMock, create_autospec, patch

import pytest
from pytest_homeassistant.common import MockConfigEntry
from schluter_wifi import SchluterClient, Thermostat

from homeassistant.core import HomeAssistant

THERMOSTAT = Thermostat("TEST123", "Bathroom", 22.5, 24, 5, 40, True, True, "1.0")
ACCOUNT = {"username": "test@example.com", "password": "test-password"}


@pytest.fixture
def mock_client() -> Generator[MagicMock]:
    """Mock the API boundary, leaving all Home Assistant behavior real."""
    client = create_autospec(SchluterClient, instance=True)
    client.async_get_thermostats.return_value = {"TEST123": THERMOSTAT}
    with (
        patch("homeassistant.components.schluter.SchluterClient", return_value=client),
        patch(
            "homeassistant.components.schluter.config_flow.SchluterClient",
            return_value=client,
        ),
    ):
        yield client


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """An account with the new stable identity."""
    return MockConfigEntry(
        domain="schluter", data=ACCOUNT, unique_id="test@example.com"
    )


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> MockConfigEntry:
    """Set up through Home Assistant's entry lifecycle."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
