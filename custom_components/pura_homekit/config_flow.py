"""Config flow for Pura HomeKit.

Flow steps
----------
1. ``user``          — enter Pura account email + password.
2. ``select_device`` — pick which diffuser to configure.

One config entry is created per physical diffuser so each device has its own
coordinator, set of entities, and set of HomeKit accessories.  The entry stores
the account credentials (needed for Cognito token refresh) along with the
selected ``device_id`` and ``device_name`` so platforms can be set up without
an extra API lookup.

Security note
-------------
Credentials are stored encrypted by HA's built-in config-entry store.  They
are never logged, and error messages never expose password values.
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
    """Multi-step config flow for the Pura HomeKit Bridge integration.

    Step 1 validates Pura account credentials against the live API.
    Step 2 lets the user pick a diffuser from those discovered on the account.
    """

    VERSION = 1

    def __init__(self) -> None:
        self._email: str = ""
        self._password: str = ""
        self._devices: list[PuraDevice] = []

    # ── Step 1: credentials ───────────────────────────────────────────────────

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Prompt for Pura account email and password.

        Validates credentials immediately by attempting a real Cognito
        authentication and device list fetch.  Clear, actionable error keys
        are returned to the UI on failure.

        Args:
            user_input: Form values submitted by the user, or ``None`` for
                        the initial render.

        Returns:
            A :class:`~homeassistant.config_entries.ConfigFlowResult` that
            either shows the form (with optional errors) or advances to the
            device-selection step.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            email: str = user_input[CONF_EMAIL].strip().lower()
            password: str = user_input[CONF_PASSWORD]

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
                # Classify common Cognito error messages without leaking the
                # password value into logs or the UI.
                message = str(exc).lower()
                if any(keyword in message for keyword in ("password", "incorrect", "not authorized")):
                    errors["base"] = "invalid_auth"
                else:
                    errors["base"] = "unknown"
                _LOGGER.debug("Pura config-flow auth error (type only): %s", type(exc).__name__)
            except Exception:
                _LOGGER.exception("Unexpected error during Pura authentication in config flow")
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

    # ── Step 2: device selection ──────────────────────────────────────────────

    async def async_step_select_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick which Pura device to configure.

        Builds a dropdown from the devices discovered in step 1 and creates a
        config entry for the selected device.  Duplicate entries for the same
        physical device are rejected via :meth:`async_set_unique_id`.

        Args:
            user_input: Form values submitted by the user, or ``None`` for
                        the initial render.

        Returns:
            A :class:`~homeassistant.config_entries.ConfigFlowResult` that
            either shows the selection form or creates the config entry.
        """
        errors: dict[str, str] = {}

        # Map device_id → human-readable label for the dropdown.
        device_options: dict[str, str] = {
            device.device_id: f"{device.name} ({device.model.upper()})"
            for device in self._devices
        }

        if user_input is not None:
            device_id: str = user_input[CONF_DEVICE_ID]

            # Use the bare device name (without model suffix) as the entry title.
            device_name: str = next(
                (device.name for device in self._devices if device.device_id == device_id),
                "Pura Diffuser",
            )

            # Prevent duplicate config entries for the same physical device.
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
