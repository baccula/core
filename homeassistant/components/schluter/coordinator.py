"""Manage account polling and recoverable Schluter communication errors."""

from datetime import timedelta
import logging
from typing import override

from schluter_wifi import (
    AuthenticationError,
    RateLimitError,
    SchluterClient,
    SchluterError,
    Thermostat,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

type SchluterConfigEntry = ConfigEntry[SchluterCoordinator]


class SchluterCoordinator(DataUpdateCoordinator[dict[str, Thermostat]]):
    """Keep polling after transient errors; reauthenticate rejected credentials."""

    config_entry: SchluterConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: SchluterConfigEntry, client: SchluterClient
    ) -> None:
        """Initialize the account coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name="Schluter",
            update_interval=timedelta(seconds=60),
            always_update=False,
        )
        self.client = client

    @override
    async def _async_update_data(self) -> dict[str, Thermostat]:
        """Fetch current data without discarding the last successful snapshot."""
        try:
            return await self.client.async_get_thermostats()
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="invalid_auth"
            ) from err
        except RateLimitError as err:
            raise UpdateFailed(
                "Schluter rate limit reached", retry_after=err.retry_after
            ) from err
        except SchluterError as err:
            raise UpdateFailed(str(err)) from err
