"""
Pura Cloud API Client.

Based on the pypura library by natekspencer (https://github.com/natekspencer/pypura).

Authentication:
  Pura uses AWS Cognito USER_SRP_AUTH via pycognito.  The id_token is attached
  as a Bearer token on every REST request through pycognito's RequestsSrpAuth
  helper.

API:
  REST over HTTPS to https://trypura.io/mobile/api/
  Key endpoints:
    GET  v2/users/devices          → list all devices + current state
    POST devices/{id}/intensity    → set fan intensity for a bay
    POST devices/{id}/nightlight   → set nightlight state
    POST devices/{id}/stop-all     → turn off all bays

Device state (relevant fields from GET v2/users/devices):
  Each device in the returned list has:
    device_id  (str)   – unique device identifier
    name       (str)   – user-assigned room name
    type       (str)   – e.g. "pura4"
    connected  (bool)  – whether the device is online
    bays: list of bay objects:
      bay          (int)   – slot number (1 or 2)
      activeLight  (str)   – controller/bay identifier used in write calls
      intensity    (int)   – 0-10; 0 = off
      active       (bool)  – whether this bay is the currently diffusing one
      fragrance:
        name   (str)
        colors (list)  – first entry is the primary hex colour
    nightlight:
      active      (bool)
      brightness  (int)   – 1-10
      color       (str)   – hex colour string e.g. "#ffffff"
      controller  (str)   – controller identifier used in write calls

ESPHome migration path:
  Replace PuraApiClient with a local ESPHome REST/native API client that
  exposes the same public interface.  No other files need to change.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from .const import PURA_API_URL, PURA_CLIENT_ID, PURA_COGNITO_REGION, PURA_USER_POOL_ID

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class PuraFragrance:
    name: str
    color: str = "#ffffff"   # primary hex colour from the fragrance colors list


@dataclass
class PuraBay:
    slot: int               # 1 or 2
    intensity: int          # 0-10; 0 = off
    active: bool
    controller: str = ""    # activeLight value — needed for write calls
    fragrance: PuraFragrance | None = None


@dataclass
class PuraNightlight:
    on: bool
    brightness: int         # 1-10
    color: str              # hex colour string
    controller: str = ""    # controller value — needed for write calls


@dataclass
class PuraDevice:
    device_id: str
    name: str
    model: str
    connected: bool
    bays: list[PuraBay] = field(default_factory=list)
    nightlight: PuraNightlight | None = None

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    @property
    def is_on(self) -> bool:
        """True if any bay is actively diffusing (intensity > 0)."""
        return any(bay.intensity > 0 for bay in self.bays)

    @property
    def active_intensity(self) -> int:
        """Return the intensity of the active bay, or 0 if off."""
        for bay in self.bays:
            if bay.active and bay.intensity > 0:
                return bay.intensity
        intensities = [b.intensity for b in self.bays if b.intensity > 0]
        return max(intensities) if intensities else 0

    @property
    def active_bay(self) -> PuraBay | None:
        for bay in self.bays:
            if bay.active:
                return bay
        return None


# ---------------------------------------------------------------------------
# Authentication — Cognito SRP via pycognito
# ---------------------------------------------------------------------------

class _CognitoAuth:
    """Manages Cognito tokens using pycognito.Cognito directly.

    We store the Cognito user object and call check_token() in an executor
    before each request.  check_token() refreshes the id_token automatically
    when it is close to expiry — no manual timer tracking needed.

    We do NOT use RequestsSrpAuth because that is designed for the synchronous
    ``requests`` library.  We use aiohttp throughout and attach the id_token
    as a plain Bearer header ourselves.
    """

    def __init__(self, email: str, password: str) -> None:
        self._email = email
        self._password = password
        self._user: Any = None   # pycognito.Cognito, set after authenticate()

    @property
    def is_authenticated(self) -> bool:
        return self._user is not None and bool(self._user.id_token)

    async def authenticate(self) -> None:
        """Perform the initial SRP authentication in an executor thread."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._blocking_authenticate)

    def _blocking_authenticate(self) -> None:
        """Blocking SRP auth — must run in an executor, not the event loop."""
        from pycognito import Cognito  # type: ignore[import]

        user = Cognito(
            user_pool_id=PURA_USER_POOL_ID,
            client_id=PURA_CLIENT_ID,
            user_pool_region=PURA_COGNITO_REGION,
            username=self._email,
        )
        # authenticate() performs the full USER_SRP_AUTH challenge and
        # populates user.id_token, user.access_token, user.refresh_token
        user.authenticate(password=self._password)
        self._user = user
        _LOGGER.debug("Pura Cognito authentication successful for %s", self._email)

    async def get_id_token(self) -> str:
        """Return a valid id_token, refreshing automatically if close to expiry.

        Calls check_token() in an executor — it is a blocking network call that
        pycognito uses to refresh the token when it is within the expiry window.
        Falls back to full re-authentication if the refresh fails.
        """
        if not self.is_authenticated:
            await self.authenticate()

        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, self._user.check_token)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "Token check/refresh failed (%s) — re-authenticating", exc
            )
            await self.authenticate()

        token: str = self._user.id_token
        if not token:
            raise RuntimeError("Pura id_token is empty after authentication")
        return token


# ---------------------------------------------------------------------------
# Main API client
# ---------------------------------------------------------------------------

class PuraApiClient:
    """Async REST client for the Pura cloud API.

    Public interface:
        await client.async_authenticate()
        devices = await client.async_get_devices()
        await client.async_set_all_bays_intensity(device_id, intensity=5)
        await client.async_set_nightlight(device_id, on=True, brightness=7, color="#ffffff")
    """

    def __init__(
        self,
        email: str,
        password: str,
        session: aiohttp.ClientSession,
    ) -> None:
        self._session = session
        self._auth = _CognitoAuth(email, password)

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def async_authenticate(self) -> None:
        """Authenticate with Cognito. Call once at setup."""
        await self._auth.authenticate()

    # ------------------------------------------------------------------
    # Device queries
    # ------------------------------------------------------------------

    async def async_get_devices(self) -> list[PuraDevice]:
        """Fetch current state of all devices on the account.

        Calls GET https://trypura.io/mobile/api/v2/users/devices

        The response is a dict keyed by device form-factor:
          {"car": [...], "mini": [...], "plus": [...], "wall": [...]}
        We collect every device from every key.  All three Pura 4s are
        "wall" devices, but we include all types so the integration works
        regardless of which Pura models the account has.
        """
        data = await self._get("v2/users/devices")

        # Response is {type: [device, ...]} — flatten all lists into one.
        # Known type keys: "car", "mini", "plus", "wall"
        if isinstance(data, dict):
            devices = [d for device_list in data.values() for d in device_list]
        elif isinstance(data, list):
            devices = data
        else:
            _LOGGER.error("Pura: unexpected response type %s: %s", type(data), data)
            devices = []

        _LOGGER.debug("Pura: found %d device(s) across all types", len(devices))
        return [self._parse_device(d) for d in devices]

    # ------------------------------------------------------------------
    # Device commands
    # ------------------------------------------------------------------

    async def async_set_all_bays_intensity(
        self,
        device_id: str,
        intensity: int,
        bays: list[PuraBay] | None = None,
    ) -> None:
        """Set the same intensity across all bays.

        Matches homebridge-pura behaviour: syncing intensity across all bays
        keeps auto-alternate behaviour consistent.

        Args:
            device_id:  The Pura device ID string.
            intensity:  0-10.  0 turns all bays off.
            bays:       Bay list from the coordinator (needed for controller values).
                        If None, uses slot 1 and 2 with empty controller strings.
        """
        _LOGGER.debug(
            "set_all_bays_intensity device=%s intensity=%d", device_id, intensity
        )
        if bays:
            for bay in bays:
                await self._set_bay_intensity(device_id, bay, intensity)
        else:
            # Fallback when bay data not available yet
            for slot in (1, 2):
                await self._post(
                    f"devices/{device_id}/intensity",
                    json={"bay": slot, "controller": "", "intensity": intensity},
                )

    async def _set_bay_intensity(
        self,
        device_id: str,
        bay: PuraBay,
        intensity: int,
    ) -> None:
        """Set intensity for one specific bay using its controller value."""
        payload = {
            "bay": bay.slot,
            "controller": bay.controller,
            "intensity": intensity,
        }
        await self._post(f"devices/{device_id}/intensity", json=payload)

    async def async_turn_off(self, device_id: str) -> None:
        """Stop all bays on the device.

        Uses the dedicated stop-all endpoint which is cleaner than setting
        intensity to 0 on each bay individually.
        """
        _LOGGER.debug("stop_all device=%s", device_id)
        await self._post(f"devices/{device_id}/stop-all")

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

        Args:
            device_id:  The Pura device ID string.
            on:         Whether the nightlight is on.
            brightness: 1-10 brightness level.  Uses existing value if None.
            color:      Hex colour string e.g. "#ffffff".  Uses existing if None.
            nightlight: Current nightlight state from coordinator (for controller
                        value and fallback brightness/color).
        """
        current_brightness = nightlight.brightness if nightlight else 5
        current_color = nightlight.color if nightlight else "#ffffff"
        current_controller = nightlight.controller if nightlight else ""

        payload: dict[str, Any] = {
            "active": on,
            "brightness": brightness if brightness is not None else current_brightness,
            "color": color if color is not None else current_color,
            "controller": current_controller,
        }
        await self._post(f"devices/{device_id}/nightlight", json=payload)

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------

    async def _get(self, path: str) -> Any:
        """Authenticated GET to BASE_URL/path."""
        return await self._request("GET", path)

    async def _post(self, path: str, json: dict[str, Any] | None = None) -> Any:
        """Authenticated POST to BASE_URL/path."""
        return await self._request("POST", path, json=json)

    async def _request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """Execute an authenticated REST request.

        The Pura API uses the Cognito id_token as a Bearer token in the
        Authorization header.  We refresh the token in an executor thread
        before each request (pycognito handles the actual refresh logic).
        """
        # get_id_token() authenticates on first call, then checks/refreshes
        # automatically before each request — no manual expiry tracking needed.
        token = await self._auth.get_id_token()

        url = f"{PURA_API_URL}{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        _LOGGER.debug("%s %s  json=%s", method, url, json)

        try:
            async with self._session.request(
                method,
                url,
                json=json,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientError as exc:
            _LOGGER.error("Pura API request failed: %s", exc)
            raise

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_device(raw: dict[str, Any]) -> PuraDevice:
        """Parse a single device dict from the v2/users/devices response.

        Real API schema (confirmed from live response):
          deviceId       str   e.g. "24DCC3221124"
          displayName    dict  {"name": "Upstairs Diffuser", "type": "hallway"}
          connected      bool
          controller     str   e.g. "default"  — used in write calls
          bay1           dict  — slot 1 state
          bay2           dict  — slot 2 state (may be absent on single-bay models)
          deviceDefaults dict  {bay1Intensity, bay2Intensity, nightlight: {color, active, brightness}}
          fwVersion      str
          hwVersion      str

        Each bayN dict:
          code           str   fragrance code
          fragrance      dict  {name, placeholderColor, brandName, ...}
          wearingTime    int   seconds of use
          remaining      dict  {percent, days}
          lowFragrance   bool

        Intensity comes from deviceDefaults.bay1Intensity / bay2Intensity
        as a string: "off" | "subtle" | "medium" | "strong"

        Nightlight state comes from deviceDefaults.nightlight:
          {active: bool, brightness: int 1-10, color: str hex without #}
        """
        device_id = raw.get("deviceId", "")
        display_name = raw.get("displayName", {})
        name = display_name.get("name") or raw.get("name", "Pura Diffuser")
        controller = raw.get("controller", "default")
        defaults = raw.get("deviceDefaults", {})

        # ── Parse bays ───────────────────────────────────────────────────────
        #
        # Live state key: deviceDefaults.bay
        #   0        = device is OFF (no bay currently diffusing)
        #   1        = bay 1 is currently active
        #   2        = bay 2 is currently active
        #
        # Default intensity key: deviceDefaults.bay1Intensity / bay2Intensity
        #   These are the intensity SETTINGS to use when the device turns on.
        #   They are NOT the current live intensity — the device is off when
        #   bay=0 regardless of what these strings say.
        #
        # Confirmed from live response: all three offline devices have bay=0
        # and bay1Intensity='subtle'/'medium' — proving these are defaults only.

        INTENSITY_STR_TO_INT = {
            "off":    0,
            "subtle": 2,
            "medium": 5,
            "strong": 8,
        }

        active_bay_slot = defaults.get("bay", 0)  # 0=off, 1=bay1 active, 2=bay2 active

        bays: list[PuraBay] = []
        for slot, default_key in ((1, "bay1Intensity"), (2, "bay2Intensity")):
            bay_key = f"bay{slot}"
            bay_raw = raw.get(bay_key)
            if bay_raw is None:
                continue  # single-bay model — skip missing slot

            # Bay is live-active only if deviceDefaults.bay points to this slot
            is_active = (active_bay_slot == slot)

            # Intensity: use the default setting if active, 0 if off
            intensity_str = defaults.get(default_key, "off")
            intensity = INTENSITY_STR_TO_INT.get(intensity_str, 0) if is_active else 0

            fragrance: PuraFragrance | None = None
            frag_raw = bay_raw.get("fragrance")
            if frag_raw:
                # placeholderColor is a hex string WITHOUT the # prefix
                raw_color = frag_raw.get("placeholderColor", "ffffff")
                color = f"#{raw_color.lstrip('#')}"
                fragrance = PuraFragrance(
                    name=frag_raw.get("name", "Unknown"),
                    color=color,
                )

            bays.append(PuraBay(
                slot=slot,
                intensity=intensity,
                active=is_active,
                controller=controller,
                fragrance=fragrance,
            ))

        # ── Parse nightlight ─────────────────────────────────────────────────
        # Nightlight state lives in deviceDefaults.nightlight
        nightlight: PuraNightlight | None = None
        nl_defaults = defaults.get("nightlight")
        if nl_defaults is not None:
            raw_color = nl_defaults.get("color", "ffffff")
            nl_color = f"#{raw_color.lstrip('#')}"
            nightlight = PuraNightlight(
                on=nl_defaults.get("active", False),
                brightness=nl_defaults.get("brightness", 5),
                color=nl_color,
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