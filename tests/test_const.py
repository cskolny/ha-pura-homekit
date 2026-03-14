"""Tests for intensity ↔ humidity mapping constants and helpers."""
from __future__ import annotations

import pytest

from custom_components.pura_homekit.const import (
    INTENSITY_MEDIUM,
    INTENSITY_OFF,
    INTENSITY_STEPS,
    INTENSITY_STRONG,
    INTENSITY_SUBTLE,
    INTENSITY_TO_HUMIDITY,
    MODE_MEDIUM,
    MODE_OFF,
    MODE_STRONG,
    MODE_SUBTLE,
    intensity_to_mode,
)
from custom_components.pura_homekit.humidifier import _snap_to_intensity


class TestIntensityToMode:
    def test_zero_is_off(self):
        assert intensity_to_mode(0) == MODE_OFF

    def test_one_is_subtle(self):
        assert intensity_to_mode(1) == MODE_SUBTLE

    def test_three_is_subtle(self):
        assert intensity_to_mode(3) == MODE_SUBTLE

    def test_four_is_medium(self):
        assert intensity_to_mode(4) == MODE_MEDIUM

    def test_six_is_medium(self):
        assert intensity_to_mode(6) == MODE_MEDIUM

    def test_seven_is_strong(self):
        assert intensity_to_mode(7) == MODE_STRONG

    def test_ten_is_strong(self):
        assert intensity_to_mode(10) == MODE_STRONG


class TestIntensityToHumidity:
    def test_off_maps_to_zero(self):
        assert INTENSITY_TO_HUMIDITY[INTENSITY_OFF] == 0

    def test_subtle_maps_to_33(self):
        assert INTENSITY_TO_HUMIDITY[INTENSITY_SUBTLE] == 33

    def test_medium_maps_to_66(self):
        assert INTENSITY_TO_HUMIDITY[INTENSITY_MEDIUM] == 66

    def test_strong_maps_to_100(self):
        assert INTENSITY_TO_HUMIDITY[INTENSITY_STRONG] == 100


class TestSnapToIntensity:
    """Test the nearest-neighbour snapping used by async_set_humidity."""

    def test_exact_zero(self):
        assert _snap_to_intensity(0) == INTENSITY_OFF

    def test_exact_33(self):
        assert _snap_to_intensity(33) == INTENSITY_SUBTLE

    def test_exact_66(self):
        assert _snap_to_intensity(66) == INTENSITY_MEDIUM

    def test_exact_100(self):
        assert _snap_to_intensity(100) == INTENSITY_STRONG

    def test_near_zero_snaps_off(self):
        assert _snap_to_intensity(10) == INTENSITY_OFF

    def test_midpoint_33_to_66_snaps_medium(self):
        # 49.5 is equidistant; we expect it rounds toward medium (66 side)
        # 49 → closer to 33 → subtle; 50 → closer to 66 → medium
        assert _snap_to_intensity(49) == INTENSITY_SUBTLE
        assert _snap_to_intensity(50) == INTENSITY_MEDIUM

    def test_near_100_snaps_strong(self):
        assert _snap_to_intensity(90) == INTENSITY_STRONG

    def test_float_input(self):
        assert _snap_to_intensity(33.4) == INTENSITY_SUBTLE
