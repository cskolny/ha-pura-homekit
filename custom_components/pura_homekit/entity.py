"""Base entity class for Pura HomeKit entities.

All Pura entity platforms inherit from :class:`PuraEntity`, which handles
coordinator subscription, ``available`` state, and :class:`DeviceInfo`
construction.  Platform subclasses only need to implement platform-specific
state properties and service methods.
"""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PuraCoordinator
from .pura_api import PuraDevice


class PuraEntity(CoordinatorEntity[PuraCoordinator]):
    """Base class shared by all Pura HomeKit entity platforms.

    Handles:
    * Coordinator subscription and update callbacks.
    * ``available`` property (requires both coordinator data and device online).
    * :attr:`device_info` construction for the HA device registry.

    Args:
        coordinator:       The :class:`~.coordinator.PuraCoordinator` instance.
        device_id:         Unique device identifier used to look up state.
        unique_id_suffix:  Platform-specific suffix appended to the unique ID
                           (e.g. ``"humidifier"`` or ``"nightlight"``).
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PuraCoordinator,
        device_id: str,
        unique_id_suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{unique_id_suffix}"

    # ── Device registry linkage ───────────────────────────────────────────────

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information for this entity's physical device.

        Groups all entities belonging to the same physical diffuser under a
        single device entry in the HA device registry.
        """
        device = self._device
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=device.name if device else self._device_id,
            manufacturer="Pura",
            model=device.model.upper() if device else "Pura 4",
        )

    # ── Availability ──────────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        """Return ``True`` only when the coordinator has data and the device is online.

        A device that is registered but not connected (e.g. power-cycled or
        out of WiFi range) is reported as unavailable so HA shows the correct
        state in the UI and in HomeKit.
        """
        if not super().available:
            return False
        device = self._device
        return device is not None and device.connected

    # ── Helpers ───────────────────────────────────────────────────────────────

    @property
    def _device(self) -> PuraDevice | None:
        """Return the current :class:`~.pura_api.PuraDevice` from coordinator data.

        Returns ``None`` when the coordinator has not yet completed its first
        refresh or when the device is not found in the response.
        """
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._device_id)
