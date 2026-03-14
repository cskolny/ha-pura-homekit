"""
Pura Cloud API Client.

Handles authentication (AWS Cognito SRP flow) and all device commands for
Pura 4 smart fragrance diffusers.

Authentication:
  Pura uses AWS Cognito with USER_SRP_AUTH.  We use the ``warrant-lite``
  (pycognito) library to perform the SRP handshake without requiring boto3.

API:
  After authentication, all device queries and mutations are sent as
  GraphQL POSTs to ``https://api.pura.com/graphql`` with a Bearer
  ``Authorization`` header using the Cognito id_token.

Device state data model (as returned by the Pura API):
  {
    "device_id": "xxxx",
    "name": "Living Room",
    "model": "pura4",
    "connected": true,
    "bays": [
      {
        "slot": 1,
        "fragrance": {"name": "Ocean Breeze", "color": "#00aaff"},
        "intensity": 5,     # 0-10; 0 = off for this slot
        "active": true
      },
      {
        "slot": 2,
        "fragrance": {"name": "Cedar", "color": "#8b6914"},
        "intensity": 0,
        "active": false
      }
    ],
    "nightlight": {
      "on": true,
      "brightness": 7,      # 1-10
      "color": "#ffffff"    # hex RGB
    }
  }

ESPHome migration path:
  When a device is flashed with ESPHome, replace PuraApiClient usage with
  a direct ESPHome REST / native API client.  The coordinator (coordinator.py)
  is designed so only the client class needs to be swapped.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
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
    color: str  # hex colour string, e.g. "#00aaff"


@dataclass
class PuraBay:
    slot: int           # 1 or 2
    intensity: int      # 0-10; 0 = off
    active: bool
    fragrance: PuraFragrance | None = None


@dataclass
class PuraNightlight:
    on: bool
    brightness: int     # 1-10
    color: str          # hex colour string


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
        # Fall back to highest non-zero intensity
        intensities = [b.intensity for b in self.bays if b.intensity > 0]
        return max(intensities) if intensities else 0

    @property
    def active_bay(self) -> PuraBay | None:
        for bay in self.bays:
            if bay.active:
                return bay
        return None


# ---------------------------------------------------------------------------
# GraphQL queries and mutations
# ---------------------------------------------------------------------------

_GQL_GET_DEVICES = """
query GetDevices {
  devices {
    deviceId
    name
    model
    connected
    bays {
      slot
      intensity
      active
      fragrance {
        name
        color
      }
    }
    nightlight {
      on
      brightness
      color
    }
  }
}
"""

_GQL_SET_DEVICE_STATE = """
mutation SetDeviceState($input: DeviceStateInput!) {
  setDeviceState(input: $input) {
    deviceId
    bays {
      slot
      intensity
      active
    }
    nightlight {
      on
      brightness
      color
    }
  }
}
"""


# ---------------------------------------------------------------------------
# Authentication helper – Cognito SRP via warrant-lite / pycognito
# ---------------------------------------------------------------------------

class _CognitoAuth:
    """Manages Cognito authentication tokens with auto-refresh."""

    _TOKEN_REFRESH_MARGIN = timedelta(minutes=5)

    def __init__(self, email: str, password: str) -> None:
        self._email = email
        self._password = password
        self._id_token: str | None = None
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: datetime = datetime.min

    @property
    def id_token(self) -> str | None:
        return self._id_token

    def is_expired(self) -> bool:
        return datetime.utcnow() >= self._expires_at - self._TOKEN_REFRESH_MARGIN

    async def authenticate(self, session: aiohttp.ClientSession) -> None:
        """Perform Cognito USER_SRP_AUTH flow and store tokens.

        We call the Cognito IDP endpoint directly (no boto3 dependency)
        using the standard SRP challenge sequence.

        Step 1 – InitiateAuth with USER_SRP_AUTH
        Step 2 – RespondToAuthChallenge with PASSWORD_VERIFIER

        SRP maths are delegated to the warrant-lite library which ships as
        a pure-Python dependency (no AWS SDK required).
        """
        try:
            # Import here so HA can load the integration even if the package
            # isn't installed yet (will fail properly at runtime).
            from warrant.aws_srp import AWSSRP  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "The 'warrant' package is required for Pura authentication. "
                "Add 'warrant' to requirements in manifest.json."
            ) from exc

        loop = asyncio.get_event_loop()
        tokens = await loop.run_in_executor(
            None,
            self._srp_authenticate,
        )
        self._id_token = tokens["IdToken"]
        self._access_token = tokens["AccessToken"]
        self._refresh_token = tokens["RefreshToken"]
        expires_in: int = tokens.get("ExpiresIn", 3600)
        self._expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
        _LOGGER.debug("Pura Cognito authentication successful")

    def _srp_authenticate(self) -> dict[str, Any]:
        """Blocking SRP auth – run in executor to avoid blocking event loop."""
        import boto3  # type: ignore[import]
        from warrant.aws_srp import AWSSRP  # type: ignore[import]

        client = boto3.client(
            "cognito-idp",
            region_name=PURA_COGNITO_REGION,
            # No AWS credentials needed for public Cognito pools
            aws_access_key_id="PLACEHOLDER",
            aws_secret_access_key="PLACEHOLDER",
        )
        aws = AWSSRP(
            username=self._email,
            password=self._password,
            pool_id=PURA_USER_POOL_ID,
            client_id=PURA_CLIENT_ID,
            client=client,
        )
        response = aws.authenticate_user()
        return response["AuthenticationResult"]

    async def refresh(self, session: aiohttp.ClientSession) -> None:
        """Use the refresh token to get a new id_token without re-entering password."""
        if not self._refresh_token:
            await self.authenticate(session)
            return

        payload = {
            "AuthFlow": "REFRESH_TOKEN_AUTH",
            "ClientId": PURA_CLIENT_ID,
            "AuthParameters": {"REFRESH_TOKEN": self._refresh_token},
        }
        url = f"https://cognito-idp.{PURA_COGNITO_REGION}.amazonaws.com/"
        headers = {
            "Content-Type": "application/x-amz-json-1.1",
            "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
        }
        async with session.post(url, json=payload, headers=headers) as resp:
            if resp.status != 200:
                _LOGGER.warning(
                    "Token refresh failed (%s), re-authenticating", resp.status
                )
                await self.authenticate(session)
                return
            data = await resp.json()

        result = data.get("AuthenticationResult", {})
        self._id_token = result.get("IdToken", self._id_token)
        self._access_token = result.get("AccessToken", self._access_token)
        expires_in: int = result.get("ExpiresIn", 3600)
        self._expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
        _LOGGER.debug("Pura Cognito token refreshed successfully")


# ---------------------------------------------------------------------------
# Main API client
# ---------------------------------------------------------------------------

class PuraApiClient:
    """Async client for the Pura cloud API.

    Usage (inside a coordinator):
        client = PuraApiClient(email, password, session)
        await client.async_authenticate()
        devices = await client.async_get_devices()
        await client.async_set_intensity(device_id, slot=1, intensity=5)
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
        """Authenticate with Cognito and obtain API tokens."""
        await self._auth.authenticate(self._session)

    async def _ensure_token(self) -> str:
        """Return a valid id_token, refreshing if necessary."""
        if self._auth.id_token is None:
            await self._auth.authenticate(self._session)
        elif self._auth.is_expired():
            await self._auth.refresh(self._session)
        token = self._auth.id_token
        if token is None:
            raise RuntimeError("Failed to obtain Pura auth token")
        return token

    # ------------------------------------------------------------------
    # Device queries
    # ------------------------------------------------------------------

    async def async_get_devices(self) -> list[PuraDevice]:
        """Fetch the current state of all devices on the account."""
        data = await self._gql(_GQL_GET_DEVICES)
        return [self._parse_device(d) for d in data.get("devices", [])]

    # ------------------------------------------------------------------
    # Device commands
    # ------------------------------------------------------------------

    async def async_set_intensity(
        self,
        device_id: str,
        slot: int,
        intensity: int,
    ) -> None:
        """Set the intensity for a specific bay slot (0 = off, 1-10 = on).

        Args:
            device_id:  The Pura device ID string.
            slot:       Bay slot number (1 or 2).
            intensity:  0-10.  0 turns the slot off.
        """
        _LOGGER.debug(
            "set_intensity device=%s slot=%d intensity=%d",
            device_id,
            slot,
            intensity,
        )
        variables: dict[str, Any] = {
            "input": {
                "deviceId": device_id,
                "bays": [{"slot": slot, "intensity": intensity}],
            }
        }
        await self._gql(_GQL_SET_DEVICE_STATE, variables)

    async def async_set_all_bays_intensity(
        self,
        device_id: str,
        intensity: int,
    ) -> None:
        """Set the same intensity across all bays (used by HomeKit UI).

        Matches the homebridge-pura behaviour where HomeKit intensity
        changes sync across all available bays to keep auto-alternate
        behaviour consistent.
        """
        _LOGGER.debug(
            "set_all_bays_intensity device=%s intensity=%d",
            device_id,
            intensity,
        )
        variables: dict[str, Any] = {
            "input": {
                "deviceId": device_id,
                "bays": [
                    {"slot": 1, "intensity": intensity},
                    {"slot": 2, "intensity": intensity},
                ],
            }
        }
        await self._gql(_GQL_SET_DEVICE_STATE, variables)

    async def async_turn_off(self, device_id: str) -> None:
        """Turn off all bays on the device."""
        await self.async_set_all_bays_intensity(device_id, 0)

    async def async_set_nightlight(
        self,
        device_id: str,
        *,
        on: bool,
        brightness: int | None = None,
        color: str | None = None,
    ) -> None:
        """Set the device nightlight state.

        Args:
            device_id:  The Pura device ID string.
            on:         Whether the light is on.
            brightness: 1-10 brightness level (optional, keeps existing if None).
            color:      Hex colour string e.g. "#ffffff" (optional).
        """
        nightlight: dict[str, Any] = {"on": on}
        if brightness is not None:
            nightlight["brightness"] = max(1, min(10, brightness))
        if color is not None:
            nightlight["color"] = color

        variables: dict[str, Any] = {
            "input": {
                "deviceId": device_id,
                "nightlight": nightlight,
            }
        }
        await self._gql(_GQL_SET_DEVICE_STATE, variables)

    # ------------------------------------------------------------------
    # Internal GraphQL helper
    # ------------------------------------------------------------------

    async def _gql(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a GraphQL query/mutation and return ``data``."""
        token = await self._ensure_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {"query": query}
        if variables:
            body["variables"] = variables

        try:
            async with self._session.post(
                PURA_API_URL,
                json=body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                resp.raise_for_status()
                result = await resp.json()
        except aiohttp.ClientError as exc:
            _LOGGER.error("Pura API request failed: %s", exc)
            raise

        if "errors" in result:
            errors = result["errors"]
            _LOGGER.error("Pura GraphQL errors: %s", errors)
            raise RuntimeError(f"Pura API error: {errors[0].get('message', errors)}")

        return result.get("data", {})

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_device(raw: dict[str, Any]) -> PuraDevice:
        bays = [
            PuraBay(
                slot=b["slot"],
                intensity=b.get("intensity", 0),
                active=b.get("active", False),
                fragrance=(
                    PuraFragrance(
                        name=b["fragrance"]["name"],
                        color=b["fragrance"].get("color", "#ffffff"),
                    )
                    if b.get("fragrance")
                    else None
                ),
            )
            for b in raw.get("bays", [])
        ]

        nl_raw = raw.get("nightlight")
        nightlight = (
            PuraNightlight(
                on=nl_raw.get("on", False),
                brightness=nl_raw.get("brightness", 5),
                color=nl_raw.get("color", "#ffffff"),
            )
            if nl_raw
            else None
        )

        return PuraDevice(
            device_id=raw["deviceId"],
            name=raw.get("name", "Pura Diffuser"),
            model=raw.get("model", "pura4"),
            connected=raw.get("connected", False),
            bays=bays,
            nightlight=nightlight,
        )
