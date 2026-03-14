"""
Config flow for Pura HomeKit.

Steps
─────
1. ``user``          – enter Pura email + password
2. ``select_device`` – pick which diffuser to configure (one entry per device)

One config entry is created per physical diffuser.  The entry stores the
account credentials (needed for token refresh) as well as the selected
device_id and device_name so entities can be set up without an extra lookup.

Security note: credentials are stored encrypted by HA's config entry store.
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    CONF_EMAIL,
    CONF_PASSWORD,
    DOMAIN,
)
from .pura_api import PuraApiClient, PuraDevice

_LOGGER = logging.getLogger(__name__)


class PuraHomekitConfigFlow(ConfigFlow, domain=DOMAIN):
    """Multi-step config flow for Pura HomeKit."""

    VERSION = 1

    def __init__(self) -> None:
        self._email: str = ""
        self._password: str = ""
        self._devices: list[PuraDevice] = []

    # ------------------------------------------------------------------
    # Step 1 – Credentials
    # ------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Prompt for Pura account email and password."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL].strip().lower()
            password = user_input[CONF_PASSWORD]

            # Validate credentials by attempting a real authentication
            client = PuraApiClient(
                email=email,
                password=password,
                session=async_get_clientsession(self.hass),
            )
            try:
                await client.async_authenticate()
                self._devices = await client.async_get_devices()
            except aiohttp.ClientError:
                errors["base"] = "cannot_connect"
            except RuntimeError as exc:
                msg = str(exc).lower()
                if "password" in msg or "incorrect" in msg or "not authorized" in msg:
                    errors["base"] = "invalid_auth"
                else:
                    errors["base"] = "unknown"
                _LOGGER.debug("Pura auth error: %s", exc)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during Pura authentication")
                errors["base"] = "unknown"

            if not errors:
                if not self._devices:
                    return self.async_abort(reason="no_devices")

                self._email = email
                self._password = password
                return await self.async_step_select_device()

        schema = vol.Schema(
            {
                vol.Required(CONF_EMAIL): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Step 2 – Device selection
    # ------------------------------------------------------------------

    async def async_step_select_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick which Pura device to configure."""
        errors: dict[str, str] = {}

        # Build a human-readable map for the dropdown
        device_options: dict[str, str] = {
            d.device_id: f"{d.name} ({d.model.upper()})"
            for d in self._devices
        }

        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID]
            device_name_label = device_options.get(device_id, "Pura Diffuser")
            # Strip the model suffix for the friendly name stored in the entry
            device_name = next(
                (d.name for d in self._devices if d.device_id == device_id),
                "Pura Diffuser",
            )

            # Prevent duplicate entries for the same physical device
            await self.async_set_unique_id(f"{DOMAIN}_{device_id}")
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=device_name,
                data={
                    CONF_EMAIL: self._email,
                    CONF_PASSWORD: self._password,
                    CONF_DEVICE_ID: device_id,
                    CONF_DEVICE_NAME: device_name,
                },
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE_ID): vol.In(device_options),
            }
        )
        return self.async_show_form(
            step_id="select_device",
            data_schema=schema,
            errors=errors,
            description_placeholders={"device_count": str(len(self._devices))},
        )
