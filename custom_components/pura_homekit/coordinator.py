"""
DataUpdateCoordinator for Pura HomeKit.

Owns a single PuraApiClient per account config-entry and exposes per-device
data to all entity platforms.  All API calls flow through here so that
polling, error handling, and optimistic-state logic live in one place.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_EMAIL, CONF_PASSWORD, DEFAULT_SCAN_INTERVAL, DOMAIN
from .pura_api import PuraApiClient, PuraDevice

_LOGGER = logging.getLogger(__name__)


class PuraCoordinator(DataUpdateCoordinator[dict[str, PuraDevice]]):
    """Manages polling and state for all Pura devices on one account.

    ``self.data`` is a dict keyed by ``device_id`` → ``PuraDevice``.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self._entry = entry
        self.client = PuraApiClient(
            email=entry.data[CONF_EMAIL],
            password=entry.data[CONF_PASSWORD],
            session=async_get_clientsession(hass),
        )

    # ------------------------------------------------------------------
    # DataUpdateCoordinator protocol
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, PuraDevice]:
        """Fetch latest state from the Pura cloud API."""
        try:
            devices = await self.client.async_get_devices()
        except RuntimeError as exc:
            msg = str(exc)
            # Surface authentication errors so HA can prompt re-auth
            if "auth" in msg.lower() or "token" in msg.lower() or "401" in msg:
                raise ConfigEntryAuthFailed(msg) from exc
            raise UpdateFailed(f"Error communicating with Pura API: {msg}") from exc

        return {device.device_id: device for device in devices}

    # ------------------------------------------------------------------
    # Convenience command methods
    # These methods perform an optimistic state update then request a
    # coordinator refresh, matching HA best-practice for cloud integrations.
    # ------------------------------------------------------------------

    async def async_set_intensity(
        self,
        device_id: str,
        intensity: int,
    ) -> None:
        """Set diffuser intensity across all bays and refresh state."""
        await self.client.async_set_all_bays_intensity(device_id, intensity)
        await self._async_request_refresh_after_command(device_id, "intensity", intensity)

    async def async_set_nightlight(
        self,
        device_id: str,
        *,
        on: bool,
        brightness: int | None = None,
        color: str | None = None,
    ) -> None:
        """Set nightlight state and refresh."""
        await self.client.async_set_nightlight(
            device_id, on=on, brightness=brightness, color=color
        )
        await self._async_request_refresh_after_command(device_id, "nightlight_on", on)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _async_request_refresh_after_command(
        self,
        device_id: str,
        field: str,
        value: Any,
    ) -> None:
        """Optimistically patch local state then request a coordinator refresh.

        The Pura API sometimes returns stale data immediately after a command,
        so we wait 1 second before refreshing (observed in ha-pura discussion #24).
        """
        import asyncio

        # Optimistic patch so the UI updates immediately
        if self.data and device_id in self.data:
            device = self.data[device_id]
            if field == "intensity":
                for bay in device.bays:
                    bay.intensity = value
                    bay.active = value > 0
            elif field == "nightlight_on" and device.nightlight:
                device.nightlight.on = value
            self.async_set_updated_data(self.data)

        # Small delay before polling to let the Pura backend catch up
        await asyncio.sleep(1)
        await self.async_request_refresh()
