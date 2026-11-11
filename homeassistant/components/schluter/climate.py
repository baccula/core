"""Climate entities for Schluter DITRA-HEAT thermostats."""

import logging
from typing import Any, override

from schluter_wifi import AuthenticationError, SchluterError, Thermostat

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SchluterConfigEntry, SchluterCoordinator

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SchluterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add existing thermostats and discover new ones on later updates."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def async_add_new_devices() -> None:
        new = coordinator.data.keys() - known
        if new:
            known.update(new)
            async_add_entities(
                SchluterThermostat(coordinator, serial) for serial in sorted(new)
            )

    async_add_new_devices()
    entry.async_on_unload(coordinator.async_add_listener(async_add_new_devices))


class SchluterThermostat(CoordinatorEntity[SchluterCoordinator], ClimateEntity):
    """A thermostat with a stable serial identity across YAML migration."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_hvac_mode = HVACMode.HEAT
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator: SchluterCoordinator, serial_number: str) -> None:
        """Initialize with the legacy serial-number unique ID."""
        super().__init__(coordinator)
        self._serial_number = serial_number
        self._attr_unique_id = serial_number
        self._last_thermostat = coordinator.data[serial_number]
        self._device_available = self._last_thermostat.online
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial_number)},
            manufacturer="Schluter",
            name=self._last_thermostat.name,
            sw_version=self._last_thermostat.software_version,
        )

    @property
    def _thermostat(self) -> Thermostat:
        return self.coordinator.data.get(self._serial_number, self._last_thermostat)

    @override
    async def async_added_to_hass(self) -> None:
        """Report devices that were already offline at startup."""
        await super().async_added_to_hass()
        if not self._device_available:
            _LOGGER.warning("Thermostat %s is offline or missing", self.entity_id)

    @property
    @override
    def available(self) -> bool:
        return (
            super().available
            and self._serial_number in self.coordinator.data
            and self._thermostat.online
        )

    @callback
    @override
    def _handle_coordinator_update(self) -> None:
        if self.coordinator.last_update_success:
            available = (
                self._serial_number in self.coordinator.data and self._thermostat.online
            )
            if available != self._device_available:
                if available:
                    _LOGGER.info(
                        "Communication with thermostat %s restored", self.entity_id
                    )
                else:
                    _LOGGER.warning(
                        "Thermostat %s is offline or missing", self.entity_id
                    )
                self._device_available = available
            self._last_thermostat = self._thermostat
        super()._handle_coordinator_update()

    @property
    @override
    def native_current_temperature(self) -> float:
        return self._thermostat.temperature

    @property
    @override
    def native_target_temperature(self) -> float:
        return self._thermostat.target_temperature

    @property
    @override
    def min_temp(self) -> float:
        return self._thermostat.min_temperature

    @property
    @override
    def max_temp(self) -> float:
        return self._thermostat.max_temperature

    @property
    @override
    def hvac_action(self) -> HVACAction:
        return HVACAction.HEATING if self._thermostat.heating else HVACAction.IDLE

    @override
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Retain the existing heat-only mode."""

    @override
    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a permanent target and refresh the service's authoritative state."""
        try:
            await self.coordinator.client.async_set_temperature(
                self._serial_number, kwargs[ATTR_TEMPERATURE]
            )
        except AuthenticationError as err:
            self.coordinator.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="invalid_auth"
            ) from err
        except SchluterError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="set_temperature_failed"
            ) from err
        await self.coordinator.async_request_refresh()
