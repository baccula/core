"""Test startup retries, migration, and unloading."""

from datetime import timedelta
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed
from schluter_wifi import AuthenticationError, CommunicationError, RateLimitError

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from .conftest import ACCOUNT, THERMOSTAT


@pytest.mark.parametrize(
    "error", [CommunicationError("Service offline"), RateLimitError(60)]
)
async def test_setup_recovers(
    hass: HomeAssistant,
    mock_client: MagicMock,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    error: Exception,
) -> None:
    """A network outage during startup recovers on HA's scheduled retry."""
    mock_client.async_get_thermostats.side_effect = error
    config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    mock_client.async_get_thermostats.side_effect = None
    freezer.tick(timedelta(minutes=5))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("climate.bathroom").state == "heat"


async def test_setup_invalid_auth(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    """Rejected credentials require UI reauthentication."""
    mock_client.async_get_thermostats.side_effect = AuthenticationError()
    config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    assert hass.config_entries.flow.async_progress()[0]["context"]["source"] == "reauth"


@pytest.mark.usefixtures("mock_client")
async def test_yaml_migration(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    """Keep existing entity IDs, custom names, and integration identity."""
    legacy = entity_registry.async_get_or_create(
        "climate",
        "schluter",
        "TEST123",
        suggested_object_id="warm_floor",
    )
    entity_registry.async_update_entity(legacy.entity_id, name="My warm floor")
    assert await async_setup_component(hass, "schluter", {"schluter": ACCOUNT})
    await hass.async_block_till_done(wait_background_tasks=True)
    entries = hass.config_entries.async_entries("schluter")
    assert len(entries) == 1
    entity = entity_registry.async_get("climate.warm_floor")
    assert entity.unique_id == "TEST123"
    assert entity.name == "My warm floor"
    assert entity.config_entry_id == entries[0].entry_id
    assert hass.states.get("climate.warm_floor").state == "heat"
    assert hass.states.get("climate.bathroom") is None


async def test_unload(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_client: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Unloading stops polling and reloading creates no duplicate entities."""
    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    calls = mock_client.async_get_thermostats.await_count
    freezer.tick(timedelta(minutes=5))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert mock_client.async_get_thermostats.await_count == calls
    assert setup_integration.state is ConfigEntryState.NOT_LOADED
    assert await hass.config_entries.async_setup(setup_integration.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(hass.states.async_entity_ids("climate")) == 1


async def test_empty_account_discovers_later(
    hass: HomeAssistant,
    mock_client: MagicMock,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Keep polling even if no entities were present on the first refresh."""
    mock_client.async_get_thermostats.return_value = {}
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    mock_client.async_get_thermostats.return_value = {"TEST123": THERMOSTAT}
    freezer.tick(timedelta(seconds=70))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get("climate.bathroom").state == "heat"
