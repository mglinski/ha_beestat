"""Binary sensor platform for Beestat."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_LIVE, DOMAIN
from .coordinator import BeestatLiveCoordinator


@dataclass(frozen=True, kw_only=True)
class EquipmentDescription(BinarySensorEntityDescription):
    """Maps an equipment piece to its membership predicate on `running_equipment`."""

    equipment_name: str
    is_supported: Callable[[dict[str, Any]], bool]


def _has_compressor_stage(t: dict[str, Any], stage: int) -> bool:
    cool_stages = t.get("system_type_cool_stages") or 0
    heat = t.get("system_type_heat")
    heat_stages = t.get("system_type_heat_stages") or 0
    has_compressor_heat = heat in ("compressor", "geothermal")
    return cool_stages >= stage or (has_compressor_heat and heat_stages >= stage)


def _has_aux_stage(t: dict[str, Any], stage: int) -> bool:
    aux = t.get("system_type_auxiliary_heat")
    aux_stages = t.get("system_type_auxiliary_heat_stages") or 0
    if aux not in (None, "none") and aux_stages >= stage:
        return True
    # Non-heat-pump primary heat (gas/oil/electric/boiler) also runs through
    # the aux_heat circuit in beestat's data model.
    heat = t.get("system_type_heat")
    heat_stages = t.get("system_type_heat_stages") or 0
    if heat in ("gas", "oil", "electric", "boiler") and heat_stages >= stage:
        return True
    return False


EQUIPMENT_DESCRIPTIONS: tuple[EquipmentDescription, ...] = (
    EquipmentDescription(
        key="compressor_1",
        translation_key="compressor_1",
        name="Compressor stage 1",
        device_class=BinarySensorDeviceClass.RUNNING,
        equipment_name="compressor_1",
        is_supported=lambda t: _has_compressor_stage(t, 1),
    ),
    EquipmentDescription(
        key="compressor_2",
        translation_key="compressor_2",
        name="Compressor stage 2",
        device_class=BinarySensorDeviceClass.RUNNING,
        equipment_name="compressor_2",
        is_supported=lambda t: _has_compressor_stage(t, 2),
    ),
    EquipmentDescription(
        key="auxiliary_heat_1",
        translation_key="auxiliary_heat_1",
        name="Heat stage 1",
        device_class=BinarySensorDeviceClass.RUNNING,
        equipment_name="auxiliary_heat_1",
        is_supported=lambda t: _has_aux_stage(t, 1),
    ),
    EquipmentDescription(
        key="auxiliary_heat_2",
        translation_key="auxiliary_heat_2",
        name="Heat stage 2",
        device_class=BinarySensorDeviceClass.RUNNING,
        equipment_name="auxiliary_heat_2",
        is_supported=lambda t: _has_aux_stage(t, 2),
    ),
    EquipmentDescription(
        key="fan",
        translation_key="fan",
        name="Fan",
        device_class=BinarySensorDeviceClass.RUNNING,
        equipment_name="fan",
        is_supported=lambda t: True,
    ),
)


def _thermostat_device_info(thermostat_id: str, thermostat: dict[str, Any]) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"thermostat_{thermostat_id}")},
        name=thermostat.get("name") or f"Thermostat {thermostat_id}",
        manufacturer="ecobee",
    )


def _sensor_device_info(sensor_id: str, sensor: dict[str, Any]) -> DeviceInfo:
    parent_tid = sensor.get("thermostat_id")
    return DeviceInfo(
        identifiers={(DOMAIN, f"sensor_{sensor_id}")},
        name=sensor.get("name") or f"Sensor {sensor_id}",
        manufacturer="ecobee",
        via_device=(DOMAIN, f"thermostat_{parent_tid}") if parent_tid else None,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Beestat binary sensors."""
    bucket = hass.data[DOMAIN][entry.entry_id]
    live: BeestatLiveCoordinator = bucket[DATA_LIVE]

    entities: list[BinarySensorEntity] = []

    if live.data:
        for tid, thermostat in live.data.thermostats.items():
            for desc in EQUIPMENT_DESCRIPTIONS:
                if desc.is_supported(thermostat):
                    entities.append(EquipmentBinarySensor(live, entry.entry_id, tid, desc))

        for sid, sensor in live.data.sensors.items():
            if sensor.get("occupancy") is None:
                continue
            entities.append(OccupancyBinarySensor(live, entry.entry_id, sid))

    async_add_entities(entities)


class EquipmentBinarySensor(
    CoordinatorEntity[BeestatLiveCoordinator], BinarySensorEntity
):
    """On when the equipment piece appears in `running_equipment`."""

    _attr_has_entity_name = True
    entity_description: EquipmentDescription

    def __init__(
        self,
        coordinator: BeestatLiveCoordinator,
        entry_id: str,
        thermostat_id: str,
        description: EquipmentDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._thermostat_id = thermostat_id
        self._attr_unique_id = (
            f"{entry_id}_thermostat_{thermostat_id}_equipment_{description.key}"
        )

    @property
    def device_info(self) -> DeviceInfo:
        thermostat = self.coordinator.data.thermostats.get(self._thermostat_id, {})
        return _thermostat_device_info(self._thermostat_id, thermostat)

    @property
    def is_on(self) -> bool | None:
        if not self.coordinator.data:
            return None
        thermostat = self.coordinator.data.thermostats.get(self._thermostat_id)
        if thermostat is None:
            return None
        running = thermostat.get("running_equipment") or []
        if not isinstance(running, list):
            return None
        return self.entity_description.equipment_name in running

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self.coordinator.data:
            return {}
        thermostat = self.coordinator.data.thermostats.get(self._thermostat_id)
        if thermostat is None:
            return {}
        return {"running_equipment": thermostat.get("running_equipment")}

    @property
    def available(self) -> bool:
        if not super().available or not self.coordinator.data:
            return False
        thermostat = self.coordinator.data.thermostats.get(self._thermostat_id)
        return bool(thermostat) and not thermostat.get("inactive")


class OccupancyBinarySensor(
    CoordinatorEntity[BeestatLiveCoordinator], BinarySensorEntity
):
    """Occupancy state from a remote sensor."""

    _attr_has_entity_name = True
    _attr_translation_key = "occupancy"
    _attr_name = "Occupancy"
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    def __init__(
        self,
        coordinator: BeestatLiveCoordinator,
        entry_id: str,
        sensor_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._sensor_id = sensor_id
        self._attr_unique_id = f"{entry_id}_sensor_{sensor_id}_occupancy"

    @property
    def device_info(self) -> DeviceInfo:
        sensor = self.coordinator.data.sensors.get(self._sensor_id, {})
        return _sensor_device_info(self._sensor_id, sensor)

    @property
    def is_on(self) -> bool | None:
        if not self.coordinator.data:
            return None
        sensor = self.coordinator.data.sensors.get(self._sensor_id)
        if sensor is None:
            return None
        value = sensor.get("occupancy")
        if value is None:
            return None
        return bool(value)

    @property
    def available(self) -> bool:
        if not super().available or not self.coordinator.data:
            return False
        sensor = self.coordinator.data.sensors.get(self._sensor_id)
        if not sensor:
            return False
        return (
            not sensor.get("inactive")
            and sensor.get("in_use", True)
            and sensor.get("occupancy") is not None
        )
