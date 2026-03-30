"""Pura HomeKit Integration.

A standalone Home Assistant custom integration that connects directly to
the Pura cloud API and exposes Pura 4 smart diffusers as HomeKit accessories:

  * Each diffuser    → **Humidifier** accessory (fan intensity via humidity %)
  * Each nightlight  → **Light** accessory (on/off, brightness, RGB colour)

No dependency on the ha-pura HACS integration.  The only external requirement
is ``pycognito`` for AWS Cognito SRP authentication.

ESPHome migration path
----------------------
When a device is flashed with ESPHome, replace ``PuraApiClient`` in
``coordinator.py`` with a local ESPHome REST/native API client.  The rest
of the integration — entities, coordinator, config flow — needs no changes.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .const import DOMAIN, PLATFORMS
from .coordinator import PuraCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:  # noqa: ARG001
    """Global YAML setup hook — UI-only integration; YAML configuration is not supported.

    Args:
        hass:   The Home Assistant instance.
        config: The global configuration dictionary (unused).

    Returns:
        Always ``True``.
    """
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Pura HomeKit config entry (one per physical diffuser).

    Creates a :class:`~.coordinator.PuraCoordinator`, performs the initial
    Cognito authentication and first data refresh, then forwards platform setup
    to ``humidifier`` and ``light``.

    Args:
        hass:  The Home Assistant instance.
        entry: The config entry to set up.

    Returns:
        ``True`` on success.

    Raises:
        ConfigEntryAuthFailed: Propagated so HA presents a re-auth notification.
        ConfigEntryNotReady:   On any other failure during initial setup so HA
                               retries automatically.
    """
    _LOGGER.debug(
        "Setting up Pura HomeKit entry: %s (%s)", entry.title, entry.entry_id
    )

    coordinator = PuraCoordinator(hass, entry)

    try:
        # First refresh authenticates with Cognito and populates coordinator.data.
        # ConfigEntryNotReady triggers an automatic retry with exponential back-off.
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed:
        raise  # Let HA surface the re-auth notification to the user.
    except Exception as exc:
        raise ConfigEntryNotReady(
            f"Failed to connect to Pura API: {exc}"
        ) from exc

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"coordinator": coordinator}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.info("Pura HomeKit entry '%s' set up successfully", entry.title)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Pura HomeKit config entry.

    Forwards platform teardown and removes the coordinator from ``hass.data``.

    Args:
        hass:  The Home Assistant instance.
        entry: The config entry to unload.

    Returns:
        ``True`` if all platforms unloaded successfully.
    """
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
