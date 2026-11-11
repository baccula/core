"""Test GUI setup, duplicate prevention, YAML import, and reauthentication."""

from unittest.mock import MagicMock, patch

import pytest
from pytest_homeassistant.common import MockConfigEntry
from schluter_wifi import AuthenticationError, CommunicationError

from homeassistant.config_entries import SOURCE_IMPORT, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import ACCOUNT


async def test_user(hass: HomeAssistant, mock_client: MagicMock) -> None:
    """Validate the account before setup and normalize its identity."""
    result = await hass.config_entries.flow.async_init(
        "schluter", context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    with patch("homeassistant.components.schluter.async_setup_entry"):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**ACCOUNT, "username": " Test@Example.COM "}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == ACCOUNT
    assert result["result"].unique_id == "test@example.com"
    mock_client.async_get_thermostats.assert_awaited_once()


@pytest.mark.parametrize(
    ("error", "key"),
    [(AuthenticationError(), "invalid_auth"), (CommunicationError(), "cannot_connect")],
)
async def test_user_error(
    hass: HomeAssistant, mock_client: MagicMock, error: Exception, key: str
) -> None:
    """Keep the form open after a recoverable validation error."""
    mock_client.async_get_thermostats.side_effect = error
    result = await hass.config_entries.flow.async_init(
        "schluter", context={"source": SOURCE_USER}, data=ACCOUNT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": key}


@pytest.mark.usefixtures("mock_client")
@pytest.mark.parametrize("source", [SOURCE_USER, SOURCE_IMPORT])
async def test_duplicate(
    hass: HomeAssistant, config_entry: MockConfigEntry, source: str
) -> None:
    """Repeated YAML imports must not overwrite the GUI-managed password."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        "schluter",
        context={"source": source},
        data={"username": " Test@EXAMPLE.com ", "password": "old-password"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert config_entry.data == ACCOUNT


async def test_import_offline(hass: HomeAssistant, mock_client: MagicMock) -> None:
    """Preserve the account so setup retries can finish an offline YAML migration."""
    mock_client.async_get_thermostats.side_effect = CommunicationError()
    with patch("homeassistant.components.schluter.async_setup_entry"):
        result = await hass.config_entries.flow.async_init(
            "schluter", context={"source": SOURCE_IMPORT}, data=ACCOUNT
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    mock_client.async_get_thermostats.assert_not_called()


@pytest.mark.usefixtures("mock_client")
async def test_reauth(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    """Updating credentials reloads the same entry and keeps its identity."""
    config_entry.add_to_hass(hass)
    config_entry.async_start_reauth(hass)
    await hass.async_block_till_done()
    flow = hass.config_entries.flow.async_progress()[0]
    assert flow["step_id"] == "reauth_confirm"
    with patch.object(hass.config_entries, "async_reload", return_value=True) as reload:
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {"password": "new-password"}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data == {**ACCOUNT, "password": "new-password"}
    reload.assert_awaited_once_with(config_entry.entry_id)


@pytest.mark.parametrize(
    ("error", "key"),
    [(AuthenticationError(), "invalid_auth"), (CommunicationError(), "cannot_connect")],
)
async def test_reauth_error(
    hass: HomeAssistant,
    mock_client: MagicMock,
    config_entry: MockConfigEntry,
    error: Exception,
    key: str,
) -> None:
    """A failed reauthentication must leave the stored credentials intact."""
    mock_client.async_get_thermostats.side_effect = error
    config_entry.add_to_hass(hass)
    config_entry.async_start_reauth(hass)
    await hass.async_block_till_done()
    flow = hass.config_entries.flow.async_progress()[0]
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"password": "bad-password"}
    )
    assert result["errors"] == {"base": key}
    assert config_entry.data == ACCOUNT
