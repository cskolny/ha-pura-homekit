"""
Pura HomeKit Integration.

A standalone Home Assistant custom integration that connects directly to
the Pura cloud API and exposes Pura 4 smart diffusers as HomeKit accessories:

  • Each diffuser → Humidifier accessory (fan intensity via humidity %)
  • Each diffuser nightlight → Light accessory (on/off, brightness, RGB color)

No dependency on the ha-pura HACS integration.  The only external requirement
is the ``warrant`` package for AWS Cognito SRP authentication.

ESPHome migration path
──────────────────────
When a device is flashed with ESPHome, replace ``PuraApiClient`` in
coordinator.py with a local ESPHome REST/native API client.  The rest of
the integration (entities, coordinator, config flow) needs no changes.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .const import DOMAIN, PLATFORMS
from .coordinator import PuraCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Global setup hook (YAML not supported — UI only)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Pura HomeKit config entry (one per diffuser)."""
    _LOGGER.debug("Setting up Pura HomeKit entry: %s (%s)", entry.title, entry.entry_id)

    coordinator = PuraCoordinator(hass, entry)

    # Perform the first refresh.  This also authenticates with Cognito.
    # ConfigEntryNotReady will trigger an automatic retry.
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed:
        raise  # HA will present a re-auth notification to the user
    except Exception as exc:
        raise ConfigEntryNotReady(f"Failed to connect to Pura API: {exc}") from exc

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {"coordinator": coordinator}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.info("Pura HomeKit entry '%s' set up successfully", entry.title)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Pura HomeKit config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
