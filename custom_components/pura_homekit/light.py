"""
Light platform for Pura HomeKit.

Exposes the Pura 4 nightlight as a standard HA light entity.

Capabilities:
  - On / Off
  - Brightness  (HA 0-255 ↔ Pura 1-10)
  - Color       (HA HS ↔ Pura hex RGB string)

HomeKit Bridge will automatically pick up this entity and expose it as a
separate Light accessory alongside the Humidifier accessory for the diffuser.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import homeassistant.util.color as color_util

from .const import CONF_DEVICE_ID, CONF_DEVICE_NAME, DOMAIN
from .coordinator import PuraCoordinator
from .entity import PuraEntity

_LOGGER = logging.getLogger(__name__)

# Pura brightness is 1-10; HA uses 0-255
_PURA_BRIGHTNESS_MAX = 10
_HA_BRIGHTNESS_MAX = 255


def _pura_brightness_to_ha(pura: int) -> int:
    """Convert Pura 1-10 brightness to HA 0-255."""
    return round((max(1, min(10, pura)) / _PURA_BRIGHTNESS_MAX) * _HA_BRIGHTNESS_MAX)


def _ha_brightness_to_pura(ha: int) -> int:
    """Convert HA 0-255 brightness to Pura 1-10 (minimum 1 when on)."""
    return max(1, round((ha / _HA_BRIGHTNESS_MAX) * _PURA_BRIGHTNESS_MAX))


def _hex_to_hs(hex_color: str) -> tuple[float, float] | None:
    """Convert a '#rrggbb' hex string to (hue, saturation) tuple."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return None
    try:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
    except ValueError:
        return None
    return color_util.color_RGB_to_hs(r, g, b)


def _hs_to_hex(hue: float, saturation: float) -> str:
    """Convert HS color (HA convention) to '#rrggbb' hex string."""
    r, g, b = color_util.color_hs_to_RGB(hue, saturation)
    return f"#{r:02x}{g:02x}{b:02x}"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Pura nightlight entity from a config entry."""
    coordinator: PuraCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    device_id: str = entry.data[CONF_DEVICE_ID]
    device_name: str = entry.data[CONF_DEVICE_NAME]

    # Only add the light entity if the device actually has a nightlight.
    # We check once at setup; if nightlight is None the feature simply won't appear.
    device = coordinator.data.get(device_id) if coordinator.data else None
    if device is not None and device.nightlight is None:
        _LOGGER.debug(
            "Device '%s' has no nightlight — skipping light entity", device_name
        )
        return

    async_add_entities(
        [PuraNightlightEntity(coordinator, device_id, device_name)],
        update_before_add=True,
    )


class PuraNightlightEntity(PuraEntity, LightEntity):
    """Light entity for the Pura 4 nightlight.

    Supports on/off, brightness (mapped from Pura's 1-10 scale),
    and full RGB colour via HS color mode.
    """

    _attr_color_mode = ColorMode.HS
    _attr_supported_color_modes = {ColorMode.HS}

    def __init__(
        self,
        coordinator: PuraCoordinator,
        device_id: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator, device_id, "nightlight")
        self._attr_name = f"{device_name} Nightlight"

    # ------------------------------------------------------------------
    # State properties
    # ------------------------------------------------------------------

    @property
    def is_on(self) -> bool | None:
        device = self._device
        if device is None or device.nightlight is None:
            return None
        return device.nightlight.on

    @property
    def brightness(self) -> int | None:
        device = self._device
        if device is None or device.nightlight is None:
            return None
        return _pura_brightness_to_ha(device.nightlight.brightness)

    @property
    def hs_color(self) -> tuple[float, float] | None:
        device = self._device
        if device is None or device.nightlight is None:
            return None
        return _hex_to_hs(device.nightlight.color)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the nightlight, optionally setting brightness and/or color."""
        device = self._device
        if device is None or device.nightlight is None:
            return

        brightness_pura: int | None = None
        color_hex: str | None = None

        if ATTR_BRIGHTNESS in kwargs:
            brightness_pura = _ha_brightness_to_pura(kwargs[ATTR_BRIGHTNESS])

        if ATTR_HS_COLOR in kwargs:
            hue, sat = kwargs[ATTR_HS_COLOR]
            color_hex = _hs_to_hex(hue, sat)

        _LOGGER.debug(
            "nightlight turn_on device=%s brightness=%s color=%s",
            self._device_id,
            brightness_pura,
            color_hex,
        )
        await self.coordinator.async_set_nightlight(
            self._device_id,
            on=True,
            brightness=brightness_pura,
            color=color_hex,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the nightlight."""
        _LOGGER.debug("nightlight turn_off device=%s", self._device_id)
        await self.coordinator.async_set_nightlight(self._device_id, on=False)
