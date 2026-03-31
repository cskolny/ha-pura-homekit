"""Pura Cloud API client.

Reverse-engineered from the pypura library by natekspencer
(https://github.com/natekspencer/pypura).

Authentication
--------------
Pura uses AWS Cognito USER_SRP_AUTH — a zero-knowledge Secure Remote Password
protocol that never transmits the user's password in plaintext.  Authentication
is handled by ``pycognito.Cognito``; the resulting ``id_token`` JWT is attached
as a ``Bearer`` header on every REST request.

REST API
--------
Base URL: ``https://trypura.io/mobile/api/``
Key endpoints:
    GET  v2/users/devices          -> list all devices + current state
    POST devices/{id}/intensity    -> set fan intensity for one bay
    POST devices/{id}/nightlight   -> set nightlight state
    POST devices/{id}/stop-all     -> immediately stop all bays

Device state (relevant fields from ``GET v2/users/devices``)
------------------------------------------------------------
Each device object in the response contains:
    deviceId       str   -- unique MAC-address-style identifier
    displayName    dict  -- {"name": "Room Name", "type": "room_type"}
    connected      bool  -- whether the device is currently online
    controller     str   -- always "default" for Pura 4; passed back in writes
    bay1 / bay2    dict  -- per-bay fragrance and usage data
    deviceDefaults dict  -- live state AND default intensity settings (see below)
    fwVersion      str   -- firmware version string

Live state vs. default state (critical distinction)
----------------------------------------------------
    ``deviceDefaults.bay``           int  -- LIVE: 0=off, 1=bay1 active, 2=bay2 active
    ``deviceDefaults.bay1Intensity`` str  -- SETTING: intensity used when bay1 turns on
    ``deviceDefaults.bay2Intensity`` str  -- SETTING: intensity used when bay2 turns on
    ``deviceDefaults.nightlight``    dict -- LIVE nightlight on/off, brightness, color

ESPHome migration path
----------------------
Replace ``PuraApiClient`` with a local ESPHome REST/native API client that
exposes the same public interface.  No other files require modification.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from .const import PURA_API_BASE_URL, PURA_CLIENT_ID, PURA_COGNITO_REGION, PURA_USER_POOL_ID

_LOGGER = logging.getLogger(__name__)

# Mapping from the API's string intensity labels to canonical integer values.
_INTENSITY_LABEL_TO_INT: dict[str, int] = {
    "off": 0,
    "subtle": 2,
    "medium": 5,
    "strong": 8,
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class PuraFragrance:
    """Fragrance loaded into a single Pura bay slot.

    Attributes:
        name:  Human-readable fragrance name from the Pura product catalogue.
        color: Primary display colour as a ``#rrggbb`` hex string.
               Derived from ``placeholderColor`` in the API response (which
               omits the ``#`` prefix).
    """

    name: str
    color: str = "#ffffff"


@dataclass
class PuraBay:
    """State of one bay slot on a Pura diffuser.

    Attributes:
        slot:       Physical slot number -- ``1`` or ``2``.
        intensity:  Current diffusion intensity (0 = off, 1-10 = active).
        active:     Whether this bay is currently diffusing (live state).
        controller: Device controller string required for write API calls.
                    Always ``"default"`` on Pura 4 hardware.
        fragrance:  Fragrance data for the vial installed in this slot, or
                    ``None`` if the slot is empty.
    """

    slot: int
    intensity: int
    active: bool
    controller: str = ""
    fragrance: PuraFragrance | None = None


@dataclass
class PuraNightlight:
    """State of the Pura diffuser nightlight.

    Attributes:
        on:         Whether the nightlight is currently illuminated.
        brightness: Current brightness level on the Pura 1-10 scale.
        color:      Current colour as a ``#rrggbb`` hex string.
        controller: Device controller string required for write API calls.
    """

    on: bool
    brightness: int
    color: str
    controller: str = ""


@dataclass
class PuraDevice:
    """Full state snapshot for one Pura diffuser device.

    Attributes:
        device_id:  Unique MAC-address-style device identifier (e.g. ``"24DCC3221124"``).
        name:       User-assigned room name from ``displayName.name``.
        model:      Model string derived from the hardware version field.
        connected:  Whether the device is currently reachable via WiFi.
        bays:       List of :class:`PuraBay` objects (up to two on Pura 4).
        nightlight: Nightlight state, or ``None`` if the device has no nightlight.
    """

    device_id: str
    name: str
    model: str
    connected: bool
    bays: list[PuraBay] = field(default_factory=list)
    nightlight: PuraNightlight | None = None

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def is_on(self) -> bool:
        """Return ``True`` if any bay is currently diffusing (intensity > 0)."""
        return any(bay.intensity > 0 for bay in self.bays)

    @property
    def active_intensity(self) -> int:
        """Return the intensity of the active bay, or the highest non-zero intensity.

        Falls back to the highest intensity across all bays when no bay is
        explicitly marked active.  Returns ``0`` when the device is fully off.
        """
        for bay in self.bays:
            if bay.active and bay.intensity > 0:
                return bay.intensity
        non_zero = [bay.intensity for bay in self.bays if bay.intensity > 0]
        return max(non_zero) if non_zero else 0

    @property
    def active_bay(self) -> PuraBay | None:
        """Return the first bay marked as active, or ``None`` if all bays are off."""
        for bay in self.bays:
            if bay.active:
                return bay
        return None


# ---------------------------------------------------------------------------
# Cognito authentication
# ---------------------------------------------------------------------------


class _CognitoAuth:
    """Manages AWS Cognito tokens using pycognito.

    Uses the ``pycognito.Cognito`` object directly (rather than
    ``RequestsSrpAuth``, which is designed for the synchronous ``requests``
    library).  The ``id_token`` is attached as a plain ``Bearer`` header by
    :class:`PuraApiClient`; token refresh is delegated to ``check_token()``.

    All blocking Cognito network calls are dispatched to an executor thread so
    they never block the asyncio event loop.
    """

    def __init__(self, email: str, password: str) -> None:
        self._email = email
        self._password = password
        # Set after a successful authenticate() call.
        self._cognito_user: Any = None

    @property
    def is_authenticated(self) -> bool:
        """Return ``True`` if a valid Cognito session exists."""
        return self._cognito_user is not None and bool(self._cognito_user.id_token)

    async def authenticate(self) -> None:
        """Perform the initial SRP authentication in a thread-pool executor.

        Populates ``_cognito_user`` with a ``pycognito.Cognito`` instance that
        holds the ``id_token``, ``access_token``, and ``refresh_token``.

        Raises:
            RuntimeError: If authentication fails for any reason.
        """
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._blocking_authenticate)

    def _blocking_authenticate(self) -> None:
        """Execute the blocking SRP challenge/response exchange.

        Must be called from an executor thread -- never directly from the
        asyncio event loop.
        """
        from pycognito import Cognito

        user = Cognito(
            user_pool_id=PURA_USER_POOL_ID,
            client_id=PURA_CLIENT_ID,
            user_pool_region=PURA_COGNITO_REGION,
            username=self._email,
        )
        # authenticate() performs the full USER_SRP_AUTH challenge exchange and
        # populates user.id_token, user.access_token, user.refresh_token.
        user.authenticate(password=self._password)
        self._cognito_user = user
        _LOGGER.debug("Pura Cognito authentication successful for %s", self._email)

    async def get_id_token(self) -> str:
        """Return a valid ``id_token``, refreshing automatically near expiry.

        Calls ``pycognito.Cognito.check_token()`` in an executor before each
        use.  ``check_token()`` refreshes the token transparently when it is
        within the Cognito expiry window -- no manual timer tracking is needed.

        Falls back to a full re-authentication if ``check_token()`` raises.

        Returns:
            A valid JWT ``id_token`` string.

        Raises:
            RuntimeError: If the ``id_token`` is empty after authentication.
        """
        if not self.is_authenticated:
            await self.authenticate()

        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, self._cognito_user.check_token)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "Pura token check/refresh failed (%s) -- re-authenticating",
                exc,
            )
            await self.authenticate()

        token: str = self._cognito_user.id_token
        if not token:
            raise RuntimeError("Pura id_token is empty after authentication")
        return token


# ---------------------------------------------------------------------------
# Main API client
# ---------------------------------------------------------------------------


class PuraApiClient:
    """Async REST client for the Pura cloud API.

    All network I/O uses the ``aiohttp.ClientSession`` provided by Home
    Assistant.  Cognito token management is handled internally via
    :class:`_CognitoAuth`.

    Public interface::

        await client.async_authenticate()
        devices = await client.async_get_devices()
        await client.async_set_all_bays_intensity(device_id, intensity=5, bays=bays)
        await client.async_turn_off(device_id)
        await client.async_set_nightlight(
            device_id, on=True, brightness=7, color="#ffffff"
        )
    """

    def __init__(
        self,
        email: str,
        password: str,
        session: aiohttp.ClientSession,
    ) -> None:
        self._session = session
        self._auth = _CognitoAuth(email=email, password=password)

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def async_authenticate(self) -> None:
        """Authenticate with Cognito.

        Call once during config-entry setup.  Subsequent requests refresh the
        token automatically via :meth:`_CognitoAuth.get_id_token`.
        """
        await self._auth.authenticate()

    # ------------------------------------------------------------------
    # Device queries
    # ------------------------------------------------------------------

    async def async_get_devices(self) -> list[PuraDevice]:
        """Fetch the current state of all devices on the account.

        Calls ``GET v2/users/devices``.

        The response is a dictionary keyed by device form-factor:
        ``{"car": [...], "mini": [...], "plus": [...], "wall": [...]}``.
        All sub-lists are flattened so the caller receives a uniform list
        regardless of which Pura models are on the account.

        Returns:
            List of :class:`PuraDevice` objects, one per physical diffuser.

        Raises:
            aiohttp.ClientError: On any network-level failure.
        """
        raw_response = await self._get("v2/users/devices")

        # Flatten the form-factor dict into a single device list.
        if isinstance(raw_response, dict):
            device_dicts: list[dict[str, Any]] = [
                device
                for device_list in raw_response.values()
                for device in device_list
            ]
        elif isinstance(raw_response, list):
            device_dicts = raw_response
        else:
            _LOGGER.error(
                "Pura: unexpected response type %s from v2/users/devices: %s",
                type(raw_response),
                raw_response,
            )
            device_dicts = []

        _LOGGER.debug(
            "Pura: discovered %d device(s) across all form factors", len(device_dicts)
        )
        return [self._parse_device(device_dict) for device_dict in device_dicts]

    # ------------------------------------------------------------------
    # Device commands
    # ------------------------------------------------------------------

    async def async_set_all_bays_intensity(
        self,
        device_id: str,
        intensity: int,
        bays: list[PuraBay] | None = None,
    ) -> None:
        """Set the same diffusion intensity across all bays.

        Syncing intensity across all bays mirrors homebridge-pura behaviour and
        keeps Pura's auto-alternate mode consistent.

        Args:
            device_id: The Pura device ID string.
            intensity: Target intensity in range 0-10.  ``0`` turns all bays off.
            bays:      Current bay list from the coordinator (needed for the
                       ``controller`` field in write calls).  When ``None``, falls
                       back to sending empty controller strings for slots 1 and 2.
        """
        _LOGGER.debug(
            "Pura: set_all_bays_intensity device=%s intensity=%d bays=%s",
            device_id,
            intensity,
            bays,
        )
        if bays:
            for bay in bays:
                await self._set_bay_intensity(device_id, bay, intensity)
        else:
            _LOGGER.warning(
                "Pura: bays list is empty for device=%s — "
                "falling back to slot 1/2 with controller='default'. "
                "Bay data will be populated after the first coordinator poll.",
                device_id,
            )
            for slot in (1, 2):
                await self._post(
                    f"devices/{device_id}/intensity",
                    json={"bay": slot, "controller": "default", "intensity": intensity},
                )

    async def _set_bay_intensity(
        self,
        device_id: str,
        bay: PuraBay,
        intensity: int,
    ) -> None:
        """Set intensity for a single bay using its stored controller value.

        Args:
            device_id: The Pura device ID string.
            bay:       The :class:`PuraBay` instance to update.
            intensity: Target intensity in range 0-10.
        """
        payload: dict[str, Any] = {
            "bay": bay.slot,
            "controller": bay.controller,
            "intensity": intensity,
        }
        _LOGGER.debug(
            "Pura intensity payload: device=%s bay=%d controller=%r intensity=%d",
            device_id,
            bay.slot,
            bay.controller,
            intensity,
        )
        await self._post(f"devices/{device_id}/intensity", json=payload)

    async def async_turn_off(self, device_id: str) -> None:
        """Stop all bays on the device using the dedicated ``stop-all`` endpoint.

        Preferred over setting intensity to 0 on each bay individually because
        the dedicated endpoint is the canonical off command in the Pura API.

        Args:
            device_id: The Pura device ID string.
        """
        _LOGGER.debug("Pura: stop_all device=%s", device_id)
        await self._post(f"devices/{device_id}/stop-all")

    async def async_set_always_on(
        self,
        device_id: str,
        bay: PuraBay,
        intensity: int,
    ) -> None:
        """Turn a diffuser on indefinitely using the confirmed pypura two-step sequence.

        Confirmed from pypura v2.1.1 source (``pura.py``):

        1. ``POST devices/{id}/intensity`` — sets the intensity level for the bay.
        2. ``POST devices/{id}/always-on`` — actually starts the device diffusing.

        ``set_intensity`` alone returns ``success: True`` but does not start
        the physical device — it only updates the stored default intensity in
        the Pura cloud.  ``always-on`` is the command that triggers diffusion.

        Args:
            device_id: The Pura device ID string.
            bay:       The bay to activate (slot 1 or 2).
            intensity: Diffusion intensity in range 1-10.
        """
        # Step 1: set the intensity level for this bay.
        intensity_payload: dict[str, Any] = {
            "bay": bay.slot,
            "controller": bay.controller,
            "intensity": intensity,
        }
        _LOGGER.debug(
            "Pura always-on step 1: set intensity device=%s bay=%d intensity=%d",
            device_id,
            bay.slot,
            intensity,
        )
        await self._post(f"devices/{device_id}/intensity", json=intensity_payload)

        # Step 2: start the device on this bay.
        always_on_payload: dict[str, Any] = {"bay": bay.slot}
        _LOGGER.debug(
            "Pura always-on step 2: start device=%s bay=%d",
            device_id,
            bay.slot,
        )
        await self._post(f"devices/{device_id}/always-on", json=always_on_payload)

    async def async_set_nightlight(
        self,
        device_id: str,
        *,
        on: bool,
        brightness: int | None = None,
        color: str | None = None,
        nightlight: PuraNightlight | None = None,
    ) -> None:
        """Set the device nightlight state.

        Any argument left as ``None`` falls back to the value from ``nightlight``
        (the current coordinator state), or to a sensible default when coordinator
        data is not yet available.

        Args:
            device_id:  The Pura device ID string.
            on:         ``True`` to switch the nightlight on, ``False`` to turn it off.
            brightness: Target brightness on the Pura 1-10 scale.
            color:      Target colour as a ``#rrggbb`` hex string.
            nightlight: Current :class:`PuraNightlight` state from the coordinator,
                        used to supply the ``controller`` value and default
                        brightness/color when those arguments are ``None``.
        """
        current_brightness = nightlight.brightness if nightlight else 5
        current_color = nightlight.color if nightlight else "#ffffff"
        current_controller = nightlight.controller if nightlight else ""

        # The Pura nightlight endpoint requires the colour WITHOUT the leading
        # '#' (e.g. "FFFFFF" not "#ffffff").  We store colours with '#' internally
        # for compatibility with HA colour utilities, so strip it here before
        # sending.
        resolved_color = color if color is not None else current_color
        api_color = resolved_color.lstrip("#").upper()

        payload: dict[str, Any] = {
            "active": on,
            "brightness": brightness if brightness is not None else current_brightness,
            "color": api_color,
            "controller": current_controller,
        }
        _LOGGER.debug(
            "Pura nightlight payload device=%s active=%s brightness=%s color=%s",
            device_id,
            on,
            payload["brightness"],
            api_color,
        )
        await self._post(f"devices/{device_id}/nightlight", json=payload)

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------

    async def _get(self, path: str) -> Any:
        """Perform an authenticated GET to ``PURA_API_BASE_URL/{path}``.

        Args:
            path: Relative URL path, e.g. ``"v2/users/devices"``.

        Returns:
            Parsed JSON response body.
        """
        return await self._request("GET", path)

    async def _post(self, path: str, json: dict[str, Any] | None = None) -> Any:
        """Perform an authenticated POST to ``PURA_API_BASE_URL/{path}``.

        Args:
            path: Relative URL path, e.g. ``"devices/{id}/intensity"``.
            json: Optional JSON request body.

        Returns:
            Parsed JSON response body.
        """
        return await self._request("POST", path, json=json)

    async def _request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """Execute an authenticated REST request against the Pura API.

        Fetches a fresh (auto-refreshed) ``id_token`` before each request so
        token expiry is handled transparently without manual scheduling.

        Args:
            method: HTTP method string, e.g. ``"GET"`` or ``"POST"``.
            path:   Relative URL path appended to :const:`PURA_API_BASE_URL`.
            json:   Optional JSON-serialisable request body dict.

        Returns:
            Parsed JSON response body.

        Raises:
            aiohttp.ClientError: On connection failures or non-2xx HTTP status.
        """
        token = await self._auth.get_id_token()
        url = f"{PURA_API_BASE_URL}{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        _LOGGER.debug("Pura API %s %s  body=%s", method, url, json)

        try:
            async with self._session.request(
                method,
                url,
                json=json,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                # Read body before raise_for_status so error details are
                # available even on 4xx responses.
                try:
                    response_body = await response.json(content_type=None)
                except Exception:  # noqa: BLE001
                    response_body = await response.text()

                if not response.ok:
                    _LOGGER.error(
                        "Pura API %s %s -> HTTP %d  error_body=%s",
                        method,
                        url,
                        response.status,
                        response_body,
                    )
                    response.raise_for_status()

                _LOGGER.debug(
                    "Pura API %s %s -> HTTP %d  response=%s",
                    method,
                    url,
                    response.status,
                    response_body,
                )
                return response_body
        except aiohttp.ClientError as exc:
            _LOGGER.error("Pura API request failed [%s %s]: %s", method, url, exc)
            raise

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_device(raw: dict[str, Any]) -> PuraDevice:
        """Parse a single device dict from the ``v2/users/devices`` response.

        Confirmed schema (from live Pura 4 responses):

        .. code-block:: json

            {
              "deviceId":    "24DCC3221124",
              "displayName": {"name": "Upstairs Diffuser", "type": "hallway"},
              "connected":   true,
              "controller":  "default",
              "bay1":        {<bay object>},
              "bay2":        {<bay object>},
              "deviceDefaults": {
                "bay":           0,
                "bay1Intensity": "subtle",
                "bay2Intensity": "subtle",
                "nightlight": {
                  "active":     false,
                  "brightness": 10,
                  "color":      "FFFFFF"
                }
              },
              "fwVersion": "7.5.3",
              "hwVersion": "4.3"
            }

        Live state vs. default state:
            ``deviceDefaults.bay`` is the live active-bay indicator
            (0 = off, 1 = bay 1 diffusing, 2 = bay 2 diffusing).
            ``deviceDefaults.bay1Intensity`` / ``bay2Intensity`` are the
            *default intensity settings* used the next time a bay starts --
            they are NOT the current live intensity.

        Args:
            raw: Raw device dictionary from the API response.

        Returns:
            A fully populated :class:`PuraDevice` instance.
        """
        device_id: str = raw.get("deviceId", "")
        display_name: dict[str, Any] = raw.get("displayName", {})
        name: str = display_name.get("name") or raw.get("name", "Pura Diffuser")
        controller: str = raw.get("controller", "default")
        defaults: dict[str, Any] = raw.get("deviceDefaults", {})

        # Live active-bay slot: 0=off, 1=bay1 active, 2=bay2 active.
        active_bay_slot: int = defaults.get("bay", 0)
        _LOGGER.debug(
            "Pura poll: device=%s name=%r connected=%s "
            "deviceDefaults.bay=%s bay1Intensity=%r bay2Intensity=%r",
            device_id,
            name,
            raw.get("connected"),
            active_bay_slot,
            defaults.get("bay1Intensity"),
            defaults.get("bay2Intensity"),
        )

        # ------------------------------------------------------------------
        # Parse bay slots
        # ------------------------------------------------------------------
        bays: list[PuraBay] = []
        for slot, default_key in ((1, "bay1Intensity"), (2, "bay2Intensity")):
            bay_raw: dict[str, Any] | None = raw.get(f"bay{slot}")
            if bay_raw is None:
                # Single-bay model -- skip the missing slot silently.
                continue

            is_active = active_bay_slot == slot
            intensity_label: str = defaults.get(default_key, "off")
            # Intensity is non-zero only for the live-active bay.
            intensity: int = (
                _INTENSITY_LABEL_TO_INT.get(intensity_label, 0) if is_active else 0
            )

            fragrance: PuraFragrance | None = None
            fragrance_raw: dict[str, Any] | None = bay_raw.get("fragrance")
            if fragrance_raw:
                # ``placeholderColor`` is a hex string without the ``#`` prefix.
                raw_color: str = fragrance_raw.get("placeholderColor", "ffffff")
                fragrance = PuraFragrance(
                    name=fragrance_raw.get("name", "Unknown"),
                    color=f"#{raw_color.lstrip('#')}",
                )

            bays.append(
                PuraBay(
                    slot=slot,
                    intensity=intensity,
                    active=is_active,
                    controller=controller,
                    fragrance=fragrance,
                )
            )

        # ------------------------------------------------------------------
        # Parse nightlight
        # ------------------------------------------------------------------
        nightlight: PuraNightlight | None = None
        nightlight_defaults: dict[str, Any] | None = defaults.get("nightlight")
        if nightlight_defaults is not None:
            raw_nl_color: str = nightlight_defaults.get("color", "ffffff")
            nightlight = PuraNightlight(
                on=nightlight_defaults.get("active", False),
                brightness=nightlight_defaults.get("brightness", 5),
                color=f"#{raw_nl_color.lstrip('#')}",
                controller=controller,
            )

        return PuraDevice(
            device_id=device_id,
            name=name,
            model=f"Pura {raw.get('hwVersion', '4')}",
            connected=raw.get("connected", False),
            bays=bays,
            nightlight=nightlight,
        )
