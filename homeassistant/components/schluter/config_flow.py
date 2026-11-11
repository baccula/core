"""GUI configuration and YAML migration for Schluter."""

from typing import Any, override

import probatio
from schluter_wifi import AuthenticationError, SchluterClient, SchluterError

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN

USER_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_USERNAME): str,
        probatio.Required(probatio.Secret(CONF_PASSWORD)): str,
    }
)
PASSWORD_SCHEMA = probatio.Schema(
    {probatio.Required(probatio.Secret(CONF_PASSWORD)): str}
)


class SchluterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure one entry per Schluter account."""

    VERSION = 1

    async def _async_validate(self, data: dict[str, Any]) -> str | None:
        client = SchluterClient(
            async_get_clientsession(self.hass), data[CONF_USERNAME], data[CONF_PASSWORD]
        )
        try:
            await client.async_get_thermostats()
        except AuthenticationError:
            return "invalid_auth"
        except SchluterError:
            return "cannot_connect"
        return None

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate credentials and connectivity before creating an entry."""
        errors = {}
        if user_input is not None:
            user_input = {
                **user_input,
                CONF_USERNAME: user_input[CONF_USERNAME].strip().casefold(),
            }
            await self.async_set_unique_id(user_input[CONF_USERNAME])
            self._abort_if_unique_id_configured()
            if error := await self._async_validate(user_input):
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=user_input[CONF_USERNAME], data=user_input
                )
        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors
        )

    async def async_step_import(self, user_input: dict[str, Any]) -> ConfigFlowResult:
        """Let entry setup retry an offline account during noninteractive migration."""
        user_input = {
            **user_input,
            CONF_USERNAME: user_input[CONF_USERNAME].strip().casefold(),
        }
        await self.async_set_unique_id(user_input[CONF_USERNAME])
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=user_input[CONF_USERNAME], data=user_input)

    @override
    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Reauthenticate the existing account."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Replace the password only after validating the original account."""
        entry = self._get_reauth_entry()
        errors = {}
        if user_input is not None:
            data = {**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
            if error := await self._async_validate(data):
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=PASSWORD_SCHEMA,
            errors=errors,
            description_placeholders={"username": entry.data[CONF_USERNAME]},
        )
