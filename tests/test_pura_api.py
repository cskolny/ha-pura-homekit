"""Unit tests for the Pura API client data models and response parsing."""
from __future__ import annotations

import pytest

from custom_components.pura_homekit.pura_api import (
    PuraApiClient,
    PuraBay,
    PuraDevice,
    PuraFragrance,
    PuraNightlight,
)


# ── PuraDevice helper properties ──────────────────────────────────────────────


class TestPuraDeviceHelpers:
    """Unit tests for PuraDevice convenience properties."""

    def _make_device(
        self, intensities: list[int], actives: list[bool]
    ) -> PuraDevice:
        """Return a PuraDevice populated with synthetic bay data."""
        bays = [
            PuraBay(slot=index + 1, intensity=intensities[index], active=actives[index])
            for index in range(len(intensities))
        ]
        return PuraDevice(
            device_id="test-device",
            name="Test Room",
            model="pura4",
            connected=True,
            bays=bays,
            nightlight=None,
        )

    def test_is_on_when_any_bay_has_non_zero_intensity(self) -> None:
        device = self._make_device([5, 0], [True, False])
        assert device.is_on is True

    def test_is_off_when_all_bays_have_zero_intensity(self) -> None:
        device = self._make_device([0, 0], [False, False])
        assert device.is_on is False

    def test_active_intensity_returns_active_bay_intensity(self) -> None:
        device = self._make_device([5, 8], [True, False])
        assert device.active_intensity == 5

    def test_active_intensity_falls_back_to_highest_when_no_active_bay(self) -> None:
        """When no bay is marked active, the highest non-zero intensity should be returned."""
        device = self._make_device([3, 8], [False, False])
        assert device.active_intensity == 8

    def test_active_intensity_is_zero_when_all_bays_off(self) -> None:
        device = self._make_device([0, 0], [False, False])
        assert device.active_intensity == 0

    def test_active_bay_returns_the_first_active_bay(self) -> None:
        device = self._make_device([5, 0], [True, False])
        assert device.active_bay is not None
        assert device.active_bay.slot == 1

    def test_active_bay_is_none_when_no_bay_is_active(self) -> None:
        device = self._make_device([0, 0], [False, False])
        assert device.active_bay is None


# ── PuraApiClient._parse_device ───────────────────────────────────────────────


class TestParseDevice:
    """Unit tests for PuraApiClient._parse_device.

    Uses the live Pura 4 API response schema confirmed from real device responses.
    Tests cover the complete schema including the live-state vs. default-state
    distinction documented in PURA_API.md.
    """

    def _make_raw_response(self, **overrides: object) -> dict:
        """Return a minimal but structurally correct raw device dict.

        Mirrors the real GET v2/users/devices schema. Keyword arguments
        override top-level keys.
        """
        base: dict = {
            "deviceId": "abc123",
            "displayName": {"name": "Kitchen", "type": "kitchen"},
            "connected": True,
            "controller": "default",
            "hwVersion": "4.3",
            "bay1": {
                "fragrance": {
                    "name": "Rose",
                    "placeholderColor": "ff00aa",
                },
            },
            "bay2": {
                "fragrance": None,
            },
            "deviceDefaults": {
                "bay": 1,               # bay 1 is live-active
                "bay1Intensity": "medium",
                "bay2Intensity": "subtle",
                "nightlight": {
                    "active": True,
                    "brightness": 7,
                    "color": "aabbcc",  # no # prefix — as returned by the real API
                },
            },
        }
        base.update(overrides)
        return base

    # ── Identity and connectivity ─────────────────────────────────────────────

    def test_device_id_parsed_correctly(self) -> None:
        device = PuraApiClient._parse_device(self._make_raw_response())
        assert device.device_id == "abc123"

    def test_display_name_used_as_device_name(self) -> None:
        device = PuraApiClient._parse_device(self._make_raw_response())
        assert device.name == "Kitchen"

    def test_connected_flag_parsed_correctly(self) -> None:
        device = PuraApiClient._parse_device(self._make_raw_response())
        assert device.connected is True

    def test_model_constructed_from_hw_version(self) -> None:
        device = PuraApiClient._parse_device(self._make_raw_response())
        assert "4.3" in device.model

    def test_missing_display_name_falls_back_to_default(self) -> None:
        raw = self._make_raw_response()
        del raw["displayName"]
        device = PuraApiClient._parse_device(raw)
        assert device.name == "Pura Diffuser"

    # ── Bay parsing ───────────────────────────────────────────────────────────

    def test_two_bays_parsed_from_bay1_and_bay2_keys(self) -> None:
        device = PuraApiClient._parse_device(self._make_raw_response())
        assert len(device.bays) == 2

    def test_active_bay_intensity_set_from_device_defaults(self) -> None:
        """Active bay intensity should come from deviceDefaults.bay1Intensity."""
        device = PuraApiClient._parse_device(self._make_raw_response())
        active_bay = next(b for b in device.bays if b.slot == 1)
        # bay=1 is live-active and bay1Intensity="medium" → intensity 5
        assert active_bay.intensity == 5
        assert active_bay.active is True

    def test_inactive_bay_intensity_is_zero_regardless_of_default(self) -> None:
        """Inactive bay must have intensity 0 regardless of its default setting."""
        device = PuraApiClient._parse_device(self._make_raw_response())
        inactive_bay = next(b for b in device.bays if b.slot == 2)
        assert inactive_bay.intensity == 0
        assert inactive_bay.active is False

    def test_device_off_when_bay_default_is_zero(self) -> None:
        """With deviceDefaults.bay=0, all bays must have intensity 0."""
        raw = self._make_raw_response()
        raw["deviceDefaults"]["bay"] = 0  # type: ignore[index]
        device = PuraApiClient._parse_device(raw)
        assert all(bay.intensity == 0 for bay in device.bays)
        assert device.is_on is False

    def test_missing_bay2_skipped_on_single_bay_model(self) -> None:
        raw = self._make_raw_response()
        del raw["bay2"]
        device = PuraApiClient._parse_device(raw)
        assert len(device.bays) == 1
        assert device.bays[0].slot == 1

    # ── Fragrance parsing ─────────────────────────────────────────────────────

    def test_bay1_fragrance_name_parsed(self) -> None:
        device = PuraApiClient._parse_device(self._make_raw_response())
        bay1 = next(b for b in device.bays if b.slot == 1)
        assert bay1.fragrance is not None
        assert bay1.fragrance.name == "Rose"

    def test_fragrance_color_prefixed_with_hash(self) -> None:
        """placeholderColor in the API has no # prefix — the parser must add it."""
        device = PuraApiClient._parse_device(self._make_raw_response())
        bay1 = next(b for b in device.bays if b.slot == 1)
        assert bay1.fragrance is not None
        assert bay1.fragrance.color == "#ff00aa"

    def test_bay2_with_no_fragrance_data_is_none(self) -> None:
        device = PuraApiClient._parse_device(self._make_raw_response())
        bay2 = next(b for b in device.bays if b.slot == 2)
        assert bay2.fragrance is None

    # ── Nightlight parsing ────────────────────────────────────────────────────

    def test_nightlight_on_flag_parsed(self) -> None:
        device = PuraApiClient._parse_device(self._make_raw_response())
        assert device.nightlight is not None
        assert device.nightlight.on is True

    def test_nightlight_brightness_parsed(self) -> None:
        device = PuraApiClient._parse_device(self._make_raw_response())
        assert device.nightlight is not None
        assert device.nightlight.brightness == 7

    def test_nightlight_color_prefixed_with_hash(self) -> None:
        """Nightlight color in the API has no # prefix — the parser must add it."""
        device = PuraApiClient._parse_device(self._make_raw_response())
        assert device.nightlight is not None
        assert device.nightlight.color == "#aabbcc"

    def test_nightlight_color_already_prefixed_is_not_double_prefixed(self) -> None:
        """If a # prefix is somehow already present it must not be doubled."""
        raw = self._make_raw_response()
        raw["deviceDefaults"]["nightlight"]["color"] = "#aabbcc"  # type: ignore[index]
        device = PuraApiClient._parse_device(raw)
        assert device.nightlight is not None
        assert device.nightlight.color == "#aabbcc"

    def test_nightlight_none_value_in_defaults_yields_none(self) -> None:
        raw = self._make_raw_response()
        raw["deviceDefaults"]["nightlight"] = None  # type: ignore[index]
        device = PuraApiClient._parse_device(raw)
        assert device.nightlight is None

    def test_nightlight_key_absent_from_defaults_yields_none(self) -> None:
        raw = self._make_raw_response()
        del raw["deviceDefaults"]["nightlight"]  # type: ignore[attr-defined]
        device = PuraApiClient._parse_device(raw)
        assert device.nightlight is None
