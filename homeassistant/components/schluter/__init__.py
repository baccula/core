"""The Schluter DITRA-HEAT integration."""

import probatio
from schluter_wifi import SchluterClient

from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import SchluterConfigEntry, SchluterCoordinator

PLATFORMS = [Platform.CLIMATE]

CONFIG_SCHEMA = probatio.Schema(
    {
        probatio.Optional(DOMAIN): probatio.Schema(
            {
                probatio.Required(CONF_USERNAME): cv.string,
                probatio.Required(probatio.Secret(CONF_PASSWORD)): cv.string,
            }
        )
    },
    extra=probatio.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Import legacy YAML without overwriting credentials managed in the UI."""
    if DOMAIN in config:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_IMPORT}, data=config[DOMAIN]
            )
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SchluterConfigEntry) -> None:
    """Set up an account and defer transient startup failures to HA's retries."""
    client = SchluterClient(
        async_get_clientsession(hass),
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    coordinator = SchluterCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)


async def async_unload_entry(hass: HomeAssistant, entry: SchluterConfigEntry) -> None:
    """Unload the entities and the coordinator's registered polling callbacks."""
    await hass.config_entries.async_unload_platforms_or_raise(entry, PLATFORMS)
