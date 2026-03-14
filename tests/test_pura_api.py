"""Unit tests for the Pura API client data models and parsing helpers."""
from __future__ import annotations

import pytest

from custom_components.pura_homekit.pura_api import (
    PuraApiClient,
    PuraBay,
    PuraDevice,
    PuraFragrance,
    PuraNightlight,
)


# ---------------------------------------------------------------------------
# PuraDevice helpers
# ---------------------------------------------------------------------------

class TestPuraDeviceHelpers:
    def _make_device(self, intensities: list[int], actives: list[bool]) -> PuraDevice:
        bays = [
            PuraBay(slot=i + 1, intensity=intensities[i], active=actives[i])
            for i in range(len(intensities))
        ]
        return PuraDevice(
            device_id="test",
            name="Test",
            model="pura4",
            connected=True,
            bays=bays,
            nightlight=None,
        )

    def test_is_on_when_any_bay_active(self):
        device = self._make_device([5, 0], [True, False])
        assert device.is_on is True

    def test_is_off_when_all_bays_zero(self):
        device = self._make_device([0, 0], [False, False])
        assert device.is_on is False

    def test_active_intensity_returns_active_bay(self):
        device = self._make_device([5, 8], [True, False])
        assert device.active_intensity == 5

    def test_active_intensity_fallback_to_max(self):
        """When no bay is marked active, return the highest non-zero intensity."""
        device = self._make_device([3, 8], [False, False])
        assert device.active_intensity == 8

    def test_active_intensity_zero_when_all_off(self):
        device = self._make_device([0, 0], [False, False])
        assert device.active_intensity == 0

    def test_active_bay_returns_first_active(self):
        device = self._make_device([5, 0], [True, False])
        assert device.active_bay is not None
        assert device.active_bay.slot == 1

    def test_active_bay_none_when_none_active(self):
        device = self._make_device([0, 0], [False, False])
        assert device.active_bay is None


# ---------------------------------------------------------------------------
# _parse_device
# ---------------------------------------------------------------------------

class TestParseDevice:
    def _raw(self, **overrides) -> dict:
        base = {
            "deviceId": "abc123",
            "name": "Kitchen",
            "model": "pura4",
            "connected": True,
            "bays": [
                {
                    "slot": 1,
                    "intensity": 5,
                    "active": True,
                    "fragrance": {"name": "Rose", "color": "#ff00aa"},
                },
                {
                    "slot": 2,
                    "intensity": 0,
                    "active": False,
                    "fragrance": None,
                },
            ],
            "nightlight": {"on": True, "brightness": 7, "color": "#aabbcc"},
        }
        base.update(overrides)
        return base

    def test_basic_parse(self):
        device = PuraApiClient._parse_device(self._raw())
        assert device.device_id == "abc123"
        assert device.name == "Kitchen"
        assert device.model == "pura4"
        assert device.connected is True
        assert len(device.bays) == 2

    def test_bay_fragrance_parsed(self):
        device = PuraApiClient._parse_device(self._raw())
        bay1 = device.bays[0]
        assert bay1.fragrance is not None
        assert bay1.fragrance.name == "Rose"
        assert bay1.fragrance.color == "#ff00aa"

    def test_bay_no_fragrance(self):
        device = PuraApiClient._parse_device(self._raw())
        bay2 = device.bays[1]
        assert bay2.fragrance is None

    def test_nightlight_parsed(self):
        device = PuraApiClient._parse_device(self._raw())
        assert device.nightlight is not None
        assert device.nightlight.on is True
        assert device.nightlight.brightness == 7
        assert device.nightlight.color == "#aabbcc"

    def test_missing_nightlight(self):
        device = PuraApiClient._parse_device(self._raw(nightlight=None))
        assert device.nightlight is None

    def test_missing_name_defaults(self):
        raw = self._raw()
        del raw["name"]
        device = PuraApiClient._parse_device(raw)
        assert device.name == "Pura Diffuser"
