"""Sensor platform for Beestat."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_LIVE, DATA_SUMMARY, DOMAIN
from .coordinator import BeestatLiveCoordinator, BeestatSummaryCoordinator


@dataclass(frozen=True, kw_only=True)
class BeestatThermostatSensorDescription(SensorEntityDescription):
    """Description for a sensor sourced from the live thermostat dict."""

    value_fn: Callable[[dict[str, Any]], Any]
    # If True, the entity is a temperature reading and uses the thermostat's reported unit.
    is_temperature: bool = False


@dataclass(frozen=True, kw_only=True)
class BeestatRemoteSensorDescription(SensorEntityDescription):
    """Description for a sensor sourced from the live remote-sensor dict."""

    value_fn: Callable[[dict[str, Any]], Any]
    is_temperature: bool = False


@dataclass(frozen=True, kw_only=True)
class BeestatSummaryDescription(SensorEntityDescription):
    """Description for a sensor sourced from the latest summary row."""

    value_fn: Callable[[dict[str, Any]], Any]
    is_temperature: bool = False


THERMOSTAT_SENSORS: tuple[BeestatThermostatSensorDescription, ...] = (
    BeestatThermostatSensorDescription(
        key="temperature",
        translation_key="temperature",
        name="Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        is_temperature=True,
        value_fn=lambda t: t.get("temperature"),
    ),
    BeestatThermostatSensorDescription(
        key="humidity",
        translation_key="humidity",
        name="Humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda t: t.get("humidity"),
    ),
    BeestatThermostatSensorDescription(
        key="setpoint_heat",
        translation_key="setpoint_heat",
        name="Heat setpoint",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        is_temperature=True,
        value_fn=lambda t: t.get("setpoint_heat"),
    ),
    BeestatThermostatSensorDescription(
        key="setpoint_cool",
        translation_key="setpoint_cool",
        name="Cool setpoint",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        is_temperature=True,
        value_fn=lambda t: t.get("setpoint_cool"),
    ),
)

REMOTE_SENSOR_SENSORS: tuple[BeestatRemoteSensorDescription, ...] = (
    BeestatRemoteSensorDescription(
        key="temperature",
        translation_key="temperature",
        name="Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        is_temperature=True,
        value_fn=lambda s: s.get("temperature"),
    ),
    BeestatRemoteSensorDescription(
        key="humidity",
        translation_key="humidity",
        name="Humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda s: s.get("humidity"),
    ),
)


def _heat_runtime(row: dict[str, Any]) -> float | None:
    parts = [row.get("sum_compressor_heat_1"), row.get("sum_compressor_heat_2")]
    if all(p is None for p in parts):
        return None
    return round(sum((p or 0) for p in parts) / 60.0, 1)


def _cool_runtime(row: dict[str, Any]) -> float | None:
    parts = [row.get("sum_compressor_cool_1"), row.get("sum_compressor_cool_2")]
    if all(p is None for p in parts):
        return None
    return round(sum((p or 0) for p in parts) / 60.0, 1)


def _aux_heat_runtime(row: dict[str, Any]) -> float | None:
    parts = [row.get("sum_auxiliary_heat_1"), row.get("sum_auxiliary_heat_2")]
    if all(p is None for p in parts):
        return None
    return round(sum((p or 0) for p in parts) / 60.0, 1)


def _fan_runtime(row: dict[str, Any]) -> float | None:
    seconds = row.get("sum_fan")
    return round(seconds / 60.0, 1) if seconds is not None else None


SUMMARY_SENSORS: tuple[BeestatSummaryDescription, ...] = (
    BeestatSummaryDescription(
        key="heat_runtime",
        translation_key="heat_runtime",
        name="Heat runtime (latest day)",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=1,
        value_fn=_heat_runtime,
    ),
    BeestatSummaryDescription(
        key="cool_runtime",
        translation_key="cool_runtime",
        name="Cool runtime (latest day)",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=1,
        value_fn=_cool_runtime,
    ),
    BeestatSummaryDescription(
        key="aux_heat_runtime",
        translation_key="aux_heat_runtime",
        name="Aux heat runtime (latest day)",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=1,
        value_fn=_aux_heat_runtime,
    ),
    BeestatSummaryDescription(
        key="fan_runtime",
        translation_key="fan_runtime",
        name="Fan runtime (latest day)",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=1,
        value_fn=_fan_runtime,
    ),
    BeestatSummaryDescription(
        key="avg_indoor_temperature",
        translation_key="avg_indoor_temperature",
        name="Avg indoor temperature (latest day)",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        is_temperature=True,
        value_fn=lambda r: r.get("avg_indoor_temperature"),
    ),
    BeestatSummaryDescription(
        key="avg_outdoor_temperature",
        translation_key="avg_outdoor_temperature",
        name="Avg outdoor temperature (latest day)",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=1,
        is_temperature=True,
        value_fn=lambda r: r.get("avg_outdoor_temperature"),
    ),
)


def _thermostat_unit(thermostat: dict[str, Any]) -> str:
    raw = thermostat.get("temperature_unit") or "°F"
    return UnitOfTemperature.CELSIUS if "C" in raw else UnitOfTemperature.FAHRENHEIT


def _thermostat_device_info(thermostat_id: str, thermostat: dict[str, Any]) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"thermostat_{thermostat_id}")},
        name=thermostat.get("name") or f"Thermostat {thermostat_id}",
        manufacturer="ecobee",
        model=thermostat.get("system_type_heat") or None,
        configuration_url="https://app.beestat.io/",
    )


def _sensor_device_info(
    sensor_id: str, sensor: dict[str, Any]
) -> DeviceInfo:
    parent_tid = sensor.get("thermostat_id")
    return DeviceInfo(
        identifiers={(DOMAIN, f"sensor_{sensor_id}")},
        name=sensor.get("name") or f"Sensor {sensor_id}",
        manufacturer="ecobee",
        model=sensor.get("type"),
        via_device=(DOMAIN, f"thermostat_{parent_tid}") if parent_tid else None,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Beestat sensors."""
    bucket = hass.data[DOMAIN][entry.entry_id]
    live: BeestatLiveCoordinator = bucket[DATA_LIVE]
    summary: BeestatSummaryCoordinator = bucket[DATA_SUMMARY]

    entities: list[SensorEntity] = []

    if live.data:
        for tid, thermostat in live.data.thermostats.items():
            for desc in THERMOSTAT_SENSORS:
                entities.append(
                    ThermostatSensor(live, entry.entry_id, tid, desc)
                )
            for desc in SUMMARY_SENSORS:
                entities.append(
                    SummarySensor(summary, live, entry.entry_id, tid, desc)
                )

        for sid, sensor in live.data.sensors.items():
            for desc in REMOTE_SENSOR_SENSORS:
                # Skip humidity entity if the sensor doesn't report humidity
                # (most ecobee remote sensors don't).
                if desc.key == "humidity" and sensor.get("humidity") is None:
                    continue
                if desc.key == "temperature" and sensor.get("temperature") is None:
                    continue
                entities.append(
                    RemoteSensor(live, entry.entry_id, sid, desc)
                )

    async_add_entities(entities)


class _BaseLiveEntity(CoordinatorEntity[BeestatLiveCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BeestatLiveCoordinator,
        entry_id: str,
        target_id: str,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry_id = entry_id
        self._target_id = target_id


class ThermostatSensor(_BaseLiveEntity):
    """A live sensor sourced from the thermostat record."""

    entity_description: BeestatThermostatSensorDescription

    def __init__(
        self,
        coordinator: BeestatLiveCoordinator,
        entry_id: str,
        thermostat_id: str,
        description: BeestatThermostatSensorDescription,
    ) -> None:
        super().__init__(coordinator, entry_id, thermostat_id, description)
        self._attr_unique_id = f"{entry_id}_thermostat_{thermostat_id}_{description.key}"

    @property
    def device_info(self) -> DeviceInfo:
        thermostat = self.coordinator.data.thermostats.get(self._target_id, {})
        return _thermostat_device_info(self._target_id, thermostat)

    @property
    def native_unit_of_measurement(self) -> str | None:
        if self.entity_description.is_temperature and self.coordinator.data:
            thermostat = self.coordinator.data.thermostats.get(self._target_id, {})
            return _thermostat_unit(thermostat)
        return self.entity_description.native_unit_of_measurement

    @property
    def native_value(self) -> Any:
        if not self.coordinator.data:
            return None
        thermostat = self.coordinator.data.thermostats.get(self._target_id)
        if thermostat is None:
            return None
        return self.entity_description.value_fn(thermostat)

    @property
    def available(self) -> bool:
        if not super().available or not self.coordinator.data:
            return False
        thermostat = self.coordinator.data.thermostats.get(self._target_id)
        return bool(thermostat) and not thermostat.get("inactive")


class RemoteSensor(_BaseLiveEntity):
    """A live sensor sourced from a remote sensor record."""

    entity_description: BeestatRemoteSensorDescription

    def __init__(
        self,
        coordinator: BeestatLiveCoordinator,
        entry_id: str,
        sensor_id: str,
        description: BeestatRemoteSensorDescription,
    ) -> None:
        super().__init__(coordinator, entry_id, sensor_id, description)
        self._attr_unique_id = f"{entry_id}_sensor_{sensor_id}_{description.key}"

    @property
    def device_info(self) -> DeviceInfo:
        sensor = self.coordinator.data.sensors.get(self._target_id, {})
        return _sensor_device_info(self._target_id, sensor)

    @property
    def native_unit_of_measurement(self) -> str | None:
        if self.entity_description.is_temperature and self.coordinator.data:
            sensor = self.coordinator.data.sensors.get(self._target_id, {})
            parent_tid = str(sensor.get("thermostat_id"))
            thermostat = self.coordinator.data.thermostats.get(parent_tid, {})
            return _thermostat_unit(thermostat)
        return self.entity_description.native_unit_of_measurement

    @property
    def native_value(self) -> Any:
        if not self.coordinator.data:
            return None
        sensor = self.coordinator.data.sensors.get(self._target_id)
        if sensor is None:
            return None
        return self.entity_description.value_fn(sensor)

    @property
    def available(self) -> bool:
        if not super().available or not self.coordinator.data:
            return False
        sensor = self.coordinator.data.sensors.get(self._target_id)
        if not sensor:
            return False
        return not sensor.get("inactive") and sensor.get("in_use", True)


class SummarySensor(CoordinatorEntity[BeestatSummaryCoordinator], SensorEntity):
    """A daily-summary sensor (latest available day)."""

    _attr_has_entity_name = True
    entity_description: BeestatSummaryDescription

    def __init__(
        self,
        coordinator: BeestatSummaryCoordinator,
        live: BeestatLiveCoordinator,
        entry_id: str,
        thermostat_id: str,
        description: BeestatSummaryDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._live = live
        self._entry_id = entry_id
        self._thermostat_id = thermostat_id
        self._attr_unique_id = (
            f"{entry_id}_thermostat_{thermostat_id}_summary_{description.key}"
        )

    @property
    def device_info(self) -> DeviceInfo:
        thermostat = (
            self._live.data.thermostats.get(self._thermostat_id, {})
            if self._live.data
            else {}
        )
        return _thermostat_device_info(self._thermostat_id, thermostat)

    @property
    def native_unit_of_measurement(self) -> str | None:
        if self.entity_description.is_temperature and self._live.data:
            thermostat = self._live.data.thermostats.get(self._thermostat_id, {})
            return _thermostat_unit(thermostat)
        return self.entity_description.native_unit_of_measurement

    def _latest_row(self) -> dict[str, Any] | None:
        rows = (self.coordinator.data or {}).get(self._thermostat_id) or []
        return rows[-1] if rows else None

    @property
    def native_value(self) -> Any:
        row = self._latest_row()
        if row is None:
            return None
        return self.entity_description.value_fn(row)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        row = self._latest_row()
        if row is None:
            return {}
        return {"date": row.get("date")}

    @callback
    def _handle_coordinator_update(self) -> None:
        # Defer to default; we don't need custom handling beyond
        # CoordinatorEntity's behavior.
        super()._handle_coordinator_update()
