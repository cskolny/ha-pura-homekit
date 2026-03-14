"""
Humidifier platform for Pura HomeKit.

Each Pura 4 diffuser appears in HomeKit as a Humidifier accessory.

Intensity → Humidity mapping
────────────────────────────
Pura intensity (raw 0-10) → named level → HomeKit humidity %
  0           → off     → 0 %
  1-3         → subtle  → 33 %
  4-6         → medium  → 66 %
  7-10        → strong  → 100 %

The humidity slider snaps to the nearest defined step so the user always
ends up at a valid intensity rather than a meaningless intermediate value.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.humidifier import (
    HumidifierDeviceClass,
    HumidifierEntity,
    HumidifierEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    AVAILABLE_MODES,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    DOMAIN,
    INTENSITY_OFF,
    INTENSITY_STEPS,
    INTENSITY_SUBTLE,
    MODE_OFF,
    MODE_SUBTLE,
    MODE_TO_INTENSITY,
    intensity_to_mode,
)
from .coordinator import PuraCoordinator
from .entity import PuraEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pura humidifier entity from a config entry."""
    coordinator: PuraCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    device_id: str = entry.data[CONF_DEVICE_ID]
    device_name: str = entry.data[CONF_DEVICE_NAME]

    async_add_entities(
        [PuraHumidifierEntity(coordinator, device_id, device_name)],
        update_before_add=True,
    )


def _snap_to_intensity(humidity: float) -> int:
    """Map an arbitrary 0-100 humidity value to the nearest Pura intensity int."""
    best_intensity = INTENSITY_OFF
    best_distance = abs(humidity - 0)
    for intensity, pct in INTENSITY_STEPS:
        distance = abs(humidity - pct)
        if distance < best_distance:
            best_distance = distance
            best_intensity = intensity
    return best_intensity


class PuraHumidifierEntity(PuraEntity, HumidifierEntity):
    """Humidifier entity that maps Pura diffuser intensity to HomeKit humidity %.

    Commands flow:
      HomeKit → HA humidifier service → PuraHumidifierEntity → PuraCoordinator
            → PuraApiClient → Pura GraphQL API → Pura 4 device
    """

    _attr_device_class = HumidifierDeviceClass.HUMIDIFIER
    _attr_supported_features = HumidifierEntityFeature.MODES
    _attr_available_modes = AVAILABLE_MODES
    _attr_min_humidity = 0
    _attr_max_humidity = 100
    _attr_target_humidity_step = 33

    def __init__(
        self,
        coordinator: PuraCoordinator,
        device_id: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator, device_id, "humidifier")
        self._attr_name = device_name
        # Track last active mode so turning on restores the previous intensity
        self._last_active_mode: str = MODE_SUBTLE

    # ------------------------------------------------------------------
    # State properties – derived from coordinator data
    # ------------------------------------------------------------------

    @property
    def is_on(self) -> bool | None:
        device = self._device
        return device.is_on if device else None

    @property
    def target_humidity(self) -> float | None:
        device = self._device
        if device is None:
            return None
        from .const import INTENSITY_TO_HUMIDITY
        intensity = device.active_intensity
        # Round to nearest step key
        best_pct = 0
        best_dist = abs(intensity - INTENSITY_OFF)
        for raw, pct in INTENSITY_TO_HUMIDITY.items():
            dist = abs(intensity - raw)
            if dist < best_dist:
                best_dist = dist
                best_pct = pct
        return float(best_pct)

    @property
    def current_humidity(self) -> float | None:
        """Return target as current (device has no humidity sensor)."""
        return self.target_humidity

    @property
    def mode(self) -> str | None:
        device = self._device
        if device is None:
            return None
        mode = intensity_to_mode(device.active_intensity)
        if mode != MODE_OFF:
            self._last_active_mode = mode
        return mode

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on at the last-used intensity (default: subtle)."""
        _LOGGER.debug("turn_on %s (restoring mode=%s)", self._attr_name, self._last_active_mode)
        intensity = MODE_TO_INTENSITY.get(self._last_active_mode, INTENSITY_SUBTLE)
        await self.coordinator.async_set_intensity(self._device_id, intensity)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the diffuser."""
        _LOGGER.debug("turn_off %s", self._attr_name)
        await self.coordinator.async_set_intensity(self._device_id, INTENSITY_OFF)

    async def async_set_humidity(self, humidity: int) -> None:
        """Handle HomeKit humidity slider.

        Snaps the received value to the nearest defined intensity step.
        """
        intensity = _snap_to_intensity(float(humidity))
        _LOGGER.debug(
            "set_humidity %d%% → intensity %d for %s",
            humidity,
            intensity,
            self._attr_name,
        )
        await self.coordinator.async_set_intensity(self._device_id, intensity)

    async def async_set_mode(self, mode: str) -> None:
        """Set intensity by named mode (called from HA UI / automations)."""
        _LOGGER.debug("set_mode '%s' for %s", mode, self._attr_name)
        intensity = MODE_TO_INTENSITY.get(mode)
        if intensity is None:
            _LOGGER.warning("Unknown mode '%s', ignoring", mode)
            return
        await self.coordinator.async_set_intensity(self._device_id, intensity)
