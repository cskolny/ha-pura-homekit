"""Humidifier platform for Pura HomeKit.

Each Pura 4 diffuser is exposed as a standard HA **Humidifier** entity.
HomeKit Bridge maps this to a *Humidifier* accessory with the humidity
percentage representing fan intensity.

Intensity → Humidity mapping
----------------------------
Pura internal intensity (0-10) → named level → HomeKit humidity %:

    0           → off     → 0 %
    1-3         → subtle  → 33 %
    4-6         → medium  → 66 %
    7-10        → strong  → 100 %

The HomeKit humidity slider snaps to the nearest defined step via
:func:`_snap_to_intensity`, so the user always lands on a valid intensity
rather than an undefined intermediate value.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.humidifier import (
    HumidifierDeviceClass,
    HumidifierEntity,
    HumidifierEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    AVAILABLE_MODES,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    DOMAIN,
    INTENSITY_OFF,
    INTENSITY_STEPS,
    INTENSITY_SUBTLE,
    INTENSITY_TO_HUMIDITY,
    MODE_OFF,
    MODE_SUBTLE,
    MODE_TO_INTENSITY,
    intensity_to_mode,
)
from .coordinator import PuraCoordinator
from .entity import PuraEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Pura humidifier entity from a config entry.

    Args:
        hass:               The Home Assistant instance.
        entry:              The config entry for this diffuser.
        async_add_entities: Callback to register new entities with HA.
    """
    coordinator: PuraCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    device_id: str = entry.data[CONF_DEVICE_ID]
    device_name: str = entry.data[CONF_DEVICE_NAME]

    async_add_entities(
        [PuraHumidifierEntity(coordinator, device_id, device_name)],
        update_before_add=True,
    )


def _snap_to_intensity(humidity: float) -> int:
    """Map an arbitrary 0-100 humidity value to the nearest Pura intensity integer.

    Uses linear nearest-neighbour matching against :const:`~.const.INTENSITY_STEPS`.
    This ensures that any HomeKit slider value always resolves to a valid
    Pura intensity rather than an undefined intermediate.

    Args:
        humidity: A humidity percentage value in range 0.0-100.0.

    Returns:
        The canonical Pura intensity integer closest to the given humidity.

    Example::

        >>> _snap_to_intensity(49)   # closer to 33 % → subtle
        2
        >>> _snap_to_intensity(50)   # closer to 66 % → medium
        5
    """
    best_intensity = INTENSITY_OFF
    best_distance = abs(humidity - 0)
    for intensity, humidity_pct in INTENSITY_STEPS:
        distance = abs(humidity - humidity_pct)
        if distance < best_distance:
            best_distance = distance
            best_intensity = intensity
    return best_intensity


class PuraHumidifierEntity(PuraEntity, HumidifierEntity):
    """Humidifier entity that maps Pura diffuser intensity to HomeKit humidity %.

    Command flow::

        Apple Home App
            → HA humidifier service call
            → PuraHumidifierEntity
            → PuraCoordinator
            → PuraApiClient
            → Pura REST API
            → Pura 4 device

    Attributes:
        _last_active_mode: Tracks the last non-off intensity mode so that
            :meth:`async_turn_on` can restore the previous level.
    """

    _attr_device_class = HumidifierDeviceClass.HUMIDIFIER
    _attr_supported_features = HumidifierEntityFeature.MODES
    _attr_available_modes = AVAILABLE_MODES
    _attr_min_humidity = 0
    _attr_max_humidity = 100
    _attr_target_humidity_step = 33

    def __init__(
        self,
        coordinator: PuraCoordinator,
        device_id: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator, device_id, "humidifier")
        self._attr_name = device_name
        # Remembered so that async_turn_on restores the previous intensity level.
        self._last_active_mode: str = MODE_SUBTLE

    # ── State properties ──────────────────────────────────────────────────────

    @property
    def is_on(self) -> bool | None:
        """Return ``True`` when any bay is actively diffusing."""
        device = self._device
        return device.is_on if device is not None else None

    @property
    def target_humidity(self) -> float | None:
        """Return the current intensity mapped to a HomeKit humidity percentage.

        Uses nearest-neighbour matching against :const:`~.const.INTENSITY_TO_HUMIDITY`
        so that any raw intensity value from the API always resolves to one of the
        four defined humidity steps.

        When the device is on but ``active_intensity`` momentarily resolves to 0
        (e.g. during the optimistic-patch window before a real poll confirms state),
        we floor the return value to 33 % (subtle) so the HA UI slider never sits at
        0 % while ``is_on`` is ``True``.  A slider at 0 % causes the HA humidifier
        component to emit a redundant ``set_humidity(0)`` call that would otherwise
        race with and undo the turn-on command.
        """
        device = self._device
        if device is None:
            return None

        intensity = device.active_intensity
        best_pct = 0
        best_distance = abs(intensity - INTENSITY_OFF)
        for raw_intensity, humidity_pct in INTENSITY_TO_HUMIDITY.items():
            distance = abs(intensity - raw_intensity)
            if distance < best_distance:
                best_distance = distance
                best_pct = humidity_pct

        # Floor to subtle (33 %) while the device is on so the slider is never
        # stuck at 0 % in an "on" state.
        if device.is_on and best_pct == 0:
            return float(INTENSITY_TO_HUMIDITY[INTENSITY_SUBTLE])
        return float(best_pct)

    @property
    def current_humidity(self) -> float | None:
        """Return the target humidity as current humidity.

        The Pura 4 has no ambient humidity sensor; we report the target so
        HomeKit displays a consistent value.
        """
        return self.target_humidity

    @property
    def mode(self) -> str | None:
        """Return the current named intensity mode.

        Also caches the last non-off mode so :meth:`async_turn_on` can
        restore it.
        """
        device = self._device
        if device is None:
            return None
        current_mode = intensity_to_mode(device.active_intensity)
        if current_mode != MODE_OFF:
            self._last_active_mode = current_mode
        return current_mode

    # ── Commands ──────────────────────────────────────────────────────────────

    async def async_turn_on(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Turn on at the last-used intensity level, defaulting to subtle.

        Args:
            **kwargs: Accepted but unused (required by the HA platform protocol).
        """
        _LOGGER.debug(
            "Pura turn_on %s (restoring mode=%s)", self._attr_name, self._last_active_mode
        )
        intensity = MODE_TO_INTENSITY.get(self._last_active_mode, INTENSITY_SUBTLE)
        await self.coordinator.async_set_intensity(self._device_id, intensity)

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Turn off the diffuser.

        Args:
            **kwargs: Accepted but unused (required by the HA platform protocol).
        """
        _LOGGER.debug("Pura turn_off %s", self._attr_name)
        await self.coordinator.async_set_intensity(self._device_id, INTENSITY_OFF)

    async def async_set_humidity(self, humidity: int) -> None:
        """Handle a HomeKit humidity slider change.

        Snaps the received value to the nearest defined intensity step so the
        device always receives a valid intensity integer.

        Special case: ``humidity=0`` while the device is on (or in the process
        of turning on) is treated as "restore last-used intensity" rather than
        "turn off".  Explicit turn-off always goes through :meth:`async_turn_off`.
        This prevents a spurious ``set_humidity(0)`` call — emitted by the HA
        humidifier component when ``turn_on`` is pressed while the slider sits at
        0 % — from immediately reversing the turn-on command.

        Args:
            humidity: Target humidity percentage from the HomeKit slider (0-100).
        """
        _LOGGER.debug(
            "Pura set_humidity called: humidity=%d%% device=%s is_on=%s",
            humidity,
            self._attr_name,
            self.is_on,
        )

        if humidity == 0:
            # Guard: 0 % via set_humidity means "turn off the slider display",
            # not a deliberate turn-off command.  If the device is currently on
            # (or was just optimistically turned on), restore the last intensity
            # instead of sending a stop-all command.
            if self.is_on:
                _LOGGER.debug(
                    "Pura set_humidity(0) ignored while device is on — "
                    "restoring last mode=%s for %s",
                    self._last_active_mode,
                    self._attr_name,
                )
                intensity = MODE_TO_INTENSITY.get(self._last_active_mode, INTENSITY_SUBTLE)
                await self.coordinator.async_set_intensity(self._device_id, intensity)
            else:
                _LOGGER.debug(
                    "Pura set_humidity(0) while device is off — no-op for %s",
                    self._attr_name,
                )
            return

        intensity = _snap_to_intensity(float(humidity))
        _LOGGER.debug(
            "Pura set_humidity %d%% → intensity %d for %s",
            humidity,
            intensity,
            self._attr_name,
        )
        await self.coordinator.async_set_intensity(self._device_id, intensity)

    async def async_set_mode(self, mode: str) -> None:
        """Set intensity by named mode (from HA UI, automations, or scripts).

        Args:
            mode: One of ``"subtle"``, ``"medium"``, or ``"strong"``.
                  Unknown values are logged and silently ignored.
        """
        _LOGGER.debug("Pura set_mode '%s' for %s", mode, self._attr_name)
        intensity = MODE_TO_INTENSITY.get(mode)
        if intensity is None:
            _LOGGER.warning("Pura: unknown mode '%s' received — ignoring", mode)
            return
        await self.coordinator.async_set_intensity(self._device_id, intensity)
