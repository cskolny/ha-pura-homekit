"""Tests for the nightlight brightness and color conversion helpers."""
from __future__ import annotations

import pytest

from custom_components.pura_homekit.light import (
    _ha_brightness_to_pura,
    _hex_to_hs,
    _hs_to_hex,
    _pura_brightness_to_ha,
)


class TestBrightnessConversion:
    def test_pura_min_to_ha(self):
        assert _pura_brightness_to_ha(1) == round(255 / 10)

    def test_pura_max_to_ha(self):
        assert _pura_brightness_to_ha(10) == 255

    def test_ha_max_to_pura(self):
        assert _ha_brightness_to_pura(255) == 10

    def test_ha_zero_to_pura_min(self):
        """HA brightness 0 should map to Pura minimum 1 (not 0) when turning on."""
        assert _ha_brightness_to_pura(0) == 1

    def test_pura_clamps_above_10(self):
        assert _pura_brightness_to_ha(15) == 255

    def test_pura_clamps_below_1(self):
        assert _pura_brightness_to_ha(0) == round(255 / 10)

    def test_roundtrip_midpoint(self):
        pura = 5
        ha = _pura_brightness_to_ha(pura)
        result = _ha_brightness_to_pura(ha)
        assert result == pura


class TestColorConversion:
    def test_white_hex_to_hs(self):
        hs = _hex_to_hs("#ffffff")
        assert hs is not None
        hue, sat = hs
        assert sat == pytest.approx(0, abs=1)

    def test_red_hex_to_hs(self):
        hs = _hex_to_hs("#ff0000")
        assert hs is not None
        hue, sat = hs
        assert hue == pytest.approx(0, abs=1)
        assert sat == pytest.approx(100, abs=1)

    def test_invalid_hex_returns_none(self):
        assert _hex_to_hs("notacolor") is None
        assert _hex_to_hs("#gg0000") is None

    def test_hs_to_hex_white(self):
        hex_color = _hs_to_hex(0, 0)
        assert hex_color == "#ffffff"

    def test_hs_to_hex_roundtrip(self):
        original_hex = "#ff0000"
        hs = _hex_to_hs(original_hex)
        assert hs is not None
        result = _hs_to_hex(*hs)
        # Allow minor rounding differences
        r1 = int(result[1:3], 16)
        r2 = int(original_hex[1:3], 16)
        assert abs(r1 - r2) <= 2
