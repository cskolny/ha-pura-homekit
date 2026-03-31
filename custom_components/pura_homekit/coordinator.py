"""DataUpdateCoordinator for Pura HomeKit.

Owns a single :class:`~.pura_api.PuraApiClient` per config entry and
exposes per-device state to all entity platforms.  All API calls flow
through here so that polling, error handling, and optimistic-state logic
are co-located in one place.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_EMAIL, CONF_PASSWORD, DEFAULT_SCAN_INTERVAL, DOMAIN
from .pura_api import PuraApiClient, PuraDevice

_LOGGER = logging.getLogger(__name__)


class PuraCoordinator(DataUpdateCoordinator[dict[str, PuraDevice]]):
    """Manages cloud polling and command dispatch for all Pura devices on one account.

    ``self.data`` is a mapping of ``device_id`` → :class:`~.pura_api.PuraDevice`.
    Entities should access device state exclusively through this mapping via
    :attr:`self.data`.

    Args:
        hass:  The Home Assistant instance.
        entry: The config entry that owns this coordinator.
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

    # ── DataUpdateCoordinator protocol ────────────────────────────────────────

    async def _async_update_data(self) -> dict[str, PuraDevice]:
        """Fetch the latest device state from the Pura cloud API.

        Returns:
            A mapping of ``device_id`` → :class:`~.pura_api.PuraDevice`.

        Raises:
            ConfigEntryAuthFailed: On HTTP 401 or any authentication error,
                triggering HA's built-in re-auth notification flow.
            UpdateFailed: On any other network or runtime error.
        """
        try:
            devices = await self.client.async_get_devices()
        except aiohttp.ClientResponseError as exc:
            if exc.status == 401:
                raise ConfigEntryAuthFailed("Pura authentication expired") from exc
            raise UpdateFailed(f"Pura API error (HTTP {exc.status}): {exc}") from exc
        except aiohttp.ClientError as exc:
            raise UpdateFailed(f"Pura API connection error: {exc}") from exc
        except RuntimeError as exc:
            error_message = str(exc)
            if "auth" in error_message.lower() or "token" in error_message.lower():
                raise ConfigEntryAuthFailed(error_message) from exc
            raise UpdateFailed(f"Pura API runtime error: {error_message}") from exc

        return {device.device_id: device for device in devices}

    # ── Command methods ───────────────────────────────────────────────────────
    #
    # Each method follows the same pattern:
    #   1. Issue the API command.
    #   2. Apply an optimistic state patch so the UI updates immediately.
    #   3. Schedule a delayed coordinator refresh (1 s) to confirm state from
    #      the Pura cloud, which can return stale data immediately post-command.

    async def async_set_intensity(
        self,
        device_id: str,
        intensity: int,
    ) -> None:
        """Set diffuser intensity, handling the off→on transition correctly.

        When turning on from off, only bay 1 is activated.  Sending an
        intensity command to all bays simultaneously while the device is off
        causes the firmware to ignore the command — the device needs a single
        bay nominated as the starting bay.  This matches the behaviour of the
        official Pura app.

        When the device is already on (adjusting intensity), all bays are
        updated together so the oscillation-multi-bay mode stays in sync.

        Uses the ``stop-all`` endpoint when ``intensity`` is ``0``.

        Args:
            device_id: The Pura device ID string.
            intensity: Target intensity in range 0-10.
        """
        bays = None
        device_is_on = False
        if self.data and device_id in self.data:
            bays = self.data[device_id].bays
            device_is_on = self.data[device_id].is_on

        if intensity == 0:
            await self.client.async_turn_off(device_id)
        elif not device_is_on:
            # Device is off — use the confirmed pypura two-step sequence:
            # 1. POST /intensity  — sets the intensity level for the bay
            # 2. POST /always-on  — actually starts the device diffusing
            # (confirmed from pypura v2.1.1 pura.py source)
            _LOGGER.debug(
                "Pura: device %s is off — calling always-on for bay 1",
                device_id,
            )
            bay1 = next((b for b in (bays or []) if b.slot == 1), None)
            if bay1 is not None:
                await self.client.async_set_always_on(device_id, bay1, intensity)
            else:
                # No bay data yet — post directly with known-good defaults.
                await self.client._post(
                    f"devices/{device_id}/intensity",
                    json={"bay": 1, "controller": "default", "intensity": intensity},
                )
                await self.client._post(
                    f"devices/{device_id}/always-on",
                    json={"bay": 1},
                )
        else:
            # Device is already on — update intensity across all bays so
            # oscillation-multi-bay mode stays in sync.
            await self.client.async_set_all_bays_intensity(device_id, intensity, bays=bays)

        await self._optimistic_refresh(device_id, "intensity", intensity)

    async def async_set_nightlight(
        self,
        device_id: str,
        *,
        on: bool,
        brightness: int | None = None,
        color: str | None = None,
    ) -> None:
        """Set nightlight state and schedule a coordinator refresh.

        Args:
            device_id:  The Pura device ID string.
            on:         ``True`` to turn the nightlight on; ``False`` to turn it off.
            brightness: Optional target brightness on the Pura 1-10 scale.
            color:      Optional target colour as a ``#rrggbb`` hex string.
        """
        nightlight = None
        if self.data and device_id in self.data:
            nightlight = self.data[device_id].nightlight

        await self.client.async_set_nightlight(
            device_id,
            on=on,
            brightness=brightness,
            color=color,
            nightlight=nightlight,
        )
        await self._optimistic_refresh(device_id, "nightlight_on", on)

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _optimistic_refresh(
        self,
        device_id: str,
        field: str,
        value: Any,
    ) -> None:
        """Apply an optimistic state patch and let the normal poll confirm it.

        The Pura cloud API can take several seconds to reflect a command in its
        GET response.  Firing an immediate re-poll after a command consistently
        returns the *pre-command* state, which overwrites the optimistic patch
        and makes the UI flicker back to the old value (e.g. the diffuser
        appearing to turn off immediately after a turn-on command).

        Strategy: patch local state optimistically so the UI updates at once,
        then rely on the regular 30-second coordinator poll to confirm the new
        state from the cloud.  No immediate re-poll is issued.

        Args:
            device_id: The device whose cached state should be patched.
            field:     The logical field name to update -- "intensity" or
                       "nightlight_on".
            value:     The new value for the specified field.
        """
        if not (self.data and device_id in self.data):
            return

        device = self.data[device_id]

        if field == "intensity":
            for bay in device.bays:
                bay.intensity = value
                bay.active = value > 0
        elif field == "nightlight_on" and device.nightlight is not None:
            device.nightlight.on = value

        # Push the mutated snapshot to all listeners so the UI updates at once.
        self.async_set_updated_data(self.data)
        _LOGGER.debug(
            "Pura optimistic patch applied: device=%s field=%s value=%s",
            device_id,
            field,
            value,
        )
