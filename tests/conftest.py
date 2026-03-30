"""Shared pytest fixtures for Pura HomeKit tests."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from custom_components.pura_homekit.pura_api import (
    PuraBay,
    PuraDevice,
    PuraFragrance,
    PuraNightlight,
)


# ── Device fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def pura_device_on() -> PuraDevice:
    """Return a Pura 4 device that is on at medium intensity with nightlight on."""
    return PuraDevice(
        device_id="device-abc123",
        name="Living Room",
        model="pura4",
        connected=True,
        bays=[
            PuraBay(
                slot=1,
                intensity=5,
                active=True,
                fragrance=PuraFragrance(name="Ocean Breeze", color="#00aaff"),
            ),
            PuraBay(
                slot=2,
                intensity=5,
                active=False,
                fragrance=PuraFragrance(name="Cedar", color="#8b6914"),
            ),
        ],
        nightlight=PuraNightlight(on=True, brightness=7, color="#ffffff"),
    )


@pytest.fixture
def pura_device_off() -> PuraDevice:
    """Return a Pura 4 device that is fully off with nightlight off."""
    return PuraDevice(
        device_id="device-abc123",
        name="Living Room",
        model="pura4",
        connected=True,
        bays=[
            PuraBay(
                slot=1,
                intensity=0,
                active=False,
                fragrance=PuraFragrance(name="Ocean Breeze", color="#00aaff"),
            ),
            PuraBay(
                slot=2,
                intensity=0,
                active=False,
                fragrance=PuraFragrance(name="Cedar", color="#8b6914"),
            ),
        ],
        nightlight=PuraNightlight(on=False, brightness=5, color="#ffffff"),
    )


@pytest.fixture
def pura_device_disconnected(pura_device_on: PuraDevice) -> PuraDevice:
    """Return a device that is registered but not currently connected."""
    pura_device_on.connected = False
    return pura_device_on


@pytest.fixture
def mock_api_client():
    """Return a mock PuraApiClient for use in coordinator and entity tests."""
    with patch(
        "custom_components.pura_homekit.coordinator.PuraApiClient"
    ) as mock_client_class:
        instance = mock_client_class.return_value
        instance.async_authenticate = AsyncMock()
        instance.async_get_devices = AsyncMock(return_value=[])
        instance.async_set_all_bays_intensity = AsyncMock()
        instance.async_turn_off = AsyncMock()
        instance.async_set_nightlight = AsyncMock()
        yield instance
