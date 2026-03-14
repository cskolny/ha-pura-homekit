"""Base entity for Pura HomeKit entities."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PuraCoordinator
from .pura_api import PuraDevice


class PuraEntity(CoordinatorEntity[PuraCoordinator]):
    """Base class for all Pura HomeKit entities.

    Subclasses only need to implement the platform-specific properties and
    service methods; coordinator subscription, availability, and device_info
    are all handled here.
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

    # ------------------------------------------------------------------
    # Device linkage
    # ------------------------------------------------------------------

    @property
    def device_info(self) -> DeviceInfo:
        device = self._device
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=device.name if device else self._device_id,
            manufacturer="Pura",
            model=device.model.upper() if device else "Pura 4",
        )

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        device = self._device
        return device is not None and device.connected

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def _device(self) -> PuraDevice | None:
        """Return the current PuraDevice from coordinator data."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._device_id)
