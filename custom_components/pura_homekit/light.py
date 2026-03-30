"""Light platform for Pura HomeKit.

Exposes the Pura 4 nightlight as a standard HA **Light** entity.
HomeKit Bridge maps this to a separate *Light* accessory alongside the
Humidifier accessory for the same diffuser.

Capabilities
------------
* On / Off
* Brightness (HA 0-255 ↔ Pura 1-10 scale)
* Full RGB colour (HA HS colour mode ↔ Pura ``#rrggbb`` hex string)

Brightness conversion
---------------------
Pura brightness is a 1-10 integer scale.  HA and HomeKit use 0-255.
The minimum Pura value is 1 (not 0) when the light is on, so
:func:`_ha_brightness_to_pura` clamps the result to at least ``1``.
"""
from __future__ import annotations

import logging
from typing import Any, ClassVar

import homeassistant.util.color as color_util
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DEVICE_ID, CONF_DEVICE_NAME, DOMAIN
from .coordinator import PuraCoordinator
from .entity import PuraEntity

_LOGGER = logging.getLogger(__name__)

# Pura brightness scale bounds.
_PURA_BRIGHTNESS_MIN: int = 1
_PURA_BRIGHTNESS_MAX: int = 10

# HA / HomeKit brightness scale bounds.
_HA_BRIGHTNESS_MAX: int = 255


def _pura_brightness_to_ha(pura_brightness: int) -> int:
    """Convert Pura 1-10 brightness to HA 0-255.

    Clamps the input to the valid Pura range ``[1, 10]`` before scaling.

    Args:
        pura_brightness: Pura brightness value (expected range 1-10).

    Returns:
        Equivalent brightness in the HA 0-255 range.
    """
    clamped = max(_PURA_BRIGHTNESS_MIN, min(_PURA_BRIGHTNESS_MAX, pura_brightness))
    return round((clamped / _PURA_BRIGHTNESS_MAX) * _HA_BRIGHTNESS_MAX)


def _ha_brightness_to_pura(ha_brightness: int) -> int:
    """Convert HA 0-255 brightness to Pura 1-10, clamped to minimum 1 when on.

    A HA brightness of 0 maps to Pura ``1`` rather than ``0`` because Pura
    uses ``0`` to mean "off" — brightness ``0`` while the light is on is not
    a meaningful state.

    Args:
        ha_brightness: HA brightness value in range 0-255.

    Returns:
        Equivalent brightness on the Pura 1-10 scale (minimum ``1``).
    """
    return max(
        _PURA_BRIGHTNESS_MIN,
        round((ha_brightness / _HA_BRIGHTNESS_MAX) * _PURA_BRIGHTNESS_MAX),
    )


def _hex_to_hs(hex_color: str) -> tuple[float, float] | None:
    """Convert a ``#rrggbb`` hex colour string to an ``(hue, saturation)`` tuple.

    Args:
        hex_color: Colour string with or without a leading ``#``.

    Returns:
        ``(hue, saturation)`` in the HA convention (hue 0-360, saturation 0-100),
        or ``None`` if the input is malformed.
    """
    stripped = hex_color.lstrip("#")
    if len(stripped) != 6:
        return None
    try:
        r = int(stripped[0:2], 16)
        g = int(stripped[2:4], 16)
        b = int(stripped[4:6], 16)
    except ValueError:
        return None
    return color_util.color_RGB_to_hs(r, g, b)


def _hs_to_hex(hue: float, saturation: float) -> str:
    """Convert HA HS colour to a ``#rrggbb`` hex string.

    Args:
        hue:        Hue value in range 0-360.
        saturation: Saturation value in range 0-100.

    Returns:
        Colour as a lower-case ``#rrggbb`` hex string.
    """
    r, g, b = color_util.color_hs_to_RGB(hue, saturation)
    return f"#{r:02x}{g:02x}{b:02x}"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Pura nightlight entity from a config entry.

    Skips entity creation if the device does not report nightlight hardware
    in the API response.  This is checked once at setup time; if the API later
    returns a nightlight it will not be retroactively added until the next
    config entry reload.

    Args:
        hass:               The Home Assistant instance.
        entry:              The config entry for this diffuser.
        async_add_entities: Callback to register new entities with HA.
    """
    coordinator: PuraCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    device_id: str = entry.data[CONF_DEVICE_ID]
    device_name: str = entry.data[CONF_DEVICE_NAME]

    device = coordinator.data.get(device_id) if coordinator.data else None
    if device is not None and device.nightlight is None:
        _LOGGER.debug(
            "Pura device '%s' has no nightlight — skipping light entity", device_name
        )
        return

    async_add_entities(
        [PuraNightlightEntity(coordinator, device_id, device_name)],
        update_before_add=True,
    )


class PuraNightlightEntity(PuraEntity, LightEntity):
    """Light entity for the Pura 4 nightlight.

    Supports on/off, brightness (Pura 1-10 ↔ HA 0-255), and full RGB colour
    via HS colour mode.  Colour is stored as a ``#rrggbb`` hex string by the
    API and converted to/from HA's HS convention on read and write.
    """

    _attr_color_mode = ColorMode.HS
    _attr_supported_color_modes: ClassVar[set[ColorMode]] = {ColorMode.HS}

    def __init__(
        self,
        coordinator: PuraCoordinator,
        device_id: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator, device_id, "nightlight")
        self._attr_name = f"{device_name} Nightlight"

    # ── State properties ──────────────────────────────────────────────────────

    @property
    def is_on(self) -> bool | None:
        """Return ``True`` when the nightlight is illuminated."""
        device = self._device
        if device is None or device.nightlight is None:
            return None
        return device.nightlight.on

    @property
    def brightness(self) -> int | None:
        """Return the current brightness mapped to HA 0-255 scale."""
        device = self._device
        if device is None or device.nightlight is None:
            return None
        return _pura_brightness_to_ha(device.nightlight.brightness)

    @property
    def hs_color(self) -> tuple[float, float] | None:
        """Return the current colour as an HA ``(hue, saturation)`` tuple."""
        device = self._device
        if device is None or device.nightlight is None:
            return None
        return _hex_to_hs(device.nightlight.color)

    # ── Commands ──────────────────────────────────────────────────────────────

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the nightlight, optionally updating brightness and/or colour.

        Args:
            **kwargs: May include :const:`~homeassistant.components.light.ATTR_BRIGHTNESS`
                      (HA 0-255) and/or :const:`~homeassistant.components.light.ATTR_HS_COLOR`
                      ``(hue, saturation)``.
        """
        device = self._device
        if device is None or device.nightlight is None:
            return

        brightness_pura: int | None = None
        color_hex: str | None = None

        if ATTR_BRIGHTNESS in kwargs:
            brightness_pura = _ha_brightness_to_pura(kwargs[ATTR_BRIGHTNESS])

        if ATTR_HS_COLOR in kwargs:
            hue, saturation = kwargs[ATTR_HS_COLOR]
            color_hex = _hs_to_hex(hue, saturation)

        _LOGGER.debug(
            "Pura nightlight turn_on device=%s brightness=%s color=%s",
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

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Turn off the nightlight.

        Args:
            **kwargs: Accepted but unused (required by the HA platform protocol).
        """
        _LOGGER.debug("Pura nightlight turn_off device=%s", self._device_id)
        await self.coordinator.async_set_nightlight(self._device_id, on=False)
