"""Tests for the nightlight brightness and colour conversion helpers."""
from __future__ import annotations

import pytest

from custom_components.pura_homekit.light import (
    _ha_brightness_to_pura,
    _hex_to_hs,
    _hs_to_hex,
    _pura_brightness_to_ha,
)


class TestBrightnessConversion:
    """Unit tests for Pura ↔ HA brightness scale conversion helpers."""

    def test_pura_minimum_to_ha(self) -> None:
        assert _pura_brightness_to_ha(1) == round(255 / 10)

    def test_pura_maximum_to_ha(self) -> None:
        assert _pura_brightness_to_ha(10) == 255

    def test_ha_maximum_to_pura(self) -> None:
        assert _ha_brightness_to_pura(255) == 10

    def test_ha_zero_clamps_to_pura_minimum(self) -> None:
        """HA brightness 0 must map to Pura minimum 1 (not 0) when the light is on."""
        assert _ha_brightness_to_pura(0) == 1

    def test_pura_above_10_clamps_to_255(self) -> None:
        assert _pura_brightness_to_ha(15) == 255

    def test_pura_below_1_clamps_to_minimum(self) -> None:
        assert _pura_brightness_to_ha(0) == round(255 / 10)

    def test_midpoint_roundtrip(self) -> None:
        """HA → Pura → HA roundtrip for the midpoint value should be stable."""
        pura_original = 5
        ha_value = _pura_brightness_to_ha(pura_original)
        pura_result = _ha_brightness_to_pura(ha_value)
        assert pura_result == pura_original


class TestColourConversion:
    """Unit tests for hex ↔ HS colour conversion helpers."""

    def test_white_hex_to_hs_has_zero_saturation(self) -> None:
        result = _hex_to_hs("#ffffff")
        assert result is not None
        _hue, saturation = result
        assert saturation == pytest.approx(0, abs=1)

    def test_red_hex_to_hs_hue_and_saturation(self) -> None:
        result = _hex_to_hs("#ff0000")
        assert result is not None
        hue, saturation = result
        assert hue == pytest.approx(0, abs=1)
        assert saturation == pytest.approx(100, abs=1)

    def test_malformed_hex_returns_none(self) -> None:
        assert _hex_to_hs("notacolor") is None

    def test_invalid_hex_digits_returns_none(self) -> None:
        assert _hex_to_hs("#gg0000") is None

    def test_hs_to_hex_white(self) -> None:
        assert _hs_to_hex(0, 0) == "#ffffff"

    def test_red_hs_to_hex_roundtrip(self) -> None:
        """Round-trip #ff0000 → HS → hex should give the same red channel."""
        original_hex = "#ff0000"
        hs = _hex_to_hs(original_hex)
        assert hs is not None
        result_hex = _hs_to_hex(*hs)
        original_red = int(original_hex[1:3], 16)
        result_red = int(result_hex[1:3], 16)
        # Allow for minor rounding differences introduced by the HS conversion.
        assert abs(original_red - result_red) <= 2
