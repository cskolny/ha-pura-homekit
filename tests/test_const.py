"""Tests for intensity ↔ humidity mapping constants and helper functions."""
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
    """Unit tests for :func:`~custom_components.pura_homekit.const.intensity_to_mode`."""

    def test_zero_maps_to_off(self) -> None:
        assert intensity_to_mode(0) == MODE_OFF

    def test_one_maps_to_subtle(self) -> None:
        assert intensity_to_mode(1) == MODE_SUBTLE

    def test_three_maps_to_subtle(self) -> None:
        assert intensity_to_mode(3) == MODE_SUBTLE

    def test_four_maps_to_medium(self) -> None:
        assert intensity_to_mode(4) == MODE_MEDIUM

    def test_six_maps_to_medium(self) -> None:
        assert intensity_to_mode(6) == MODE_MEDIUM

    def test_seven_maps_to_strong(self) -> None:
        assert intensity_to_mode(7) == MODE_STRONG

    def test_ten_maps_to_strong(self) -> None:
        assert intensity_to_mode(10) == MODE_STRONG


class TestIntensityToHumidity:
    """Unit tests for the :const:`~custom_components.pura_homekit.const.INTENSITY_TO_HUMIDITY` mapping."""

    def test_off_maps_to_zero_percent(self) -> None:
        assert INTENSITY_TO_HUMIDITY[INTENSITY_OFF] == 0

    def test_subtle_maps_to_33_percent(self) -> None:
        assert INTENSITY_TO_HUMIDITY[INTENSITY_SUBTLE] == 33

    def test_medium_maps_to_66_percent(self) -> None:
        assert INTENSITY_TO_HUMIDITY[INTENSITY_MEDIUM] == 66

    def test_strong_maps_to_100_percent(self) -> None:
        assert INTENSITY_TO_HUMIDITY[INTENSITY_STRONG] == 100


class TestSnapToIntensity:
    """Unit tests for :func:`~custom_components.pura_homekit.humidifier._snap_to_intensity`."""

    def test_exact_zero_maps_to_off(self) -> None:
        assert _snap_to_intensity(0) == INTENSITY_OFF

    def test_exact_33_maps_to_subtle(self) -> None:
        assert _snap_to_intensity(33) == INTENSITY_SUBTLE

    def test_exact_66_maps_to_medium(self) -> None:
        assert _snap_to_intensity(66) == INTENSITY_MEDIUM

    def test_exact_100_maps_to_strong(self) -> None:
        assert _snap_to_intensity(100) == INTENSITY_STRONG

    def test_near_zero_snaps_to_off(self) -> None:
        assert _snap_to_intensity(10) == INTENSITY_OFF

    def test_49_snaps_to_subtle(self) -> None:
        # 49 is closer to 33 % → subtle
        assert _snap_to_intensity(49) == INTENSITY_SUBTLE

    def test_50_snaps_to_medium(self) -> None:
        # 50 is closer to 66 % → medium
        assert _snap_to_intensity(50) == INTENSITY_MEDIUM

    def test_near_100_snaps_to_strong(self) -> None:
        assert _snap_to_intensity(90) == INTENSITY_STRONG

    def test_float_input_handled(self) -> None:
        assert _snap_to_intensity(33.4) == INTENSITY_SUBTLE
