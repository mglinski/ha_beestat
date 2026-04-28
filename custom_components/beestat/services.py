"""Services for Beestat: refresh and backfill_history."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import voluptuous as vol
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .api import BeestatClient, BeestatError
from .const import (
    ATTR_DAYS,
    ATTR_THERMOSTAT_ID,
    BACKFILL_DEFAULT_DAYS,
    DATA_CLIENT,
    DATA_LIVE,
    DATA_SUMMARY,
    DOMAIN,
    RUNTIME_MAX_RANGE_DAYS,
    SERVICE_BACKFILL_HISTORY,
    SERVICE_REFRESH,
)

_LOGGER = logging.getLogger(__name__)

BACKFILL_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DAYS, default=BACKFILL_DEFAULT_DAYS): vol.All(
            cv.positive_int, vol.Range(min=1, max=365)
        ),
        vol.Optional(ATTR_THERMOSTAT_ID): cv.positive_int,
    }
)


def _all_entries(hass: HomeAssistant) -> list[dict[str, Any]]:
    return list(hass.data.get(DOMAIN, {}).values())


async def _do_refresh(call: ServiceCall) -> None:
    hass = call.hass
    for entry in _all_entries(hass):
        await entry[DATA_LIVE].async_request_refresh()
        await entry[DATA_SUMMARY].async_request_refresh()


async def _do_backfill(call: ServiceCall) -> None:
    hass = call.hass
    days: int = call.data[ATTR_DAYS]
    thermostat_id_filter: int | None = call.data.get(ATTR_THERMOSTAT_ID)

    entries = _all_entries(hass)
    if not entries:
        _LOGGER.warning("No beestat config entries are loaded; nothing to backfill")
        return

    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)

    for entry in entries:
        client: BeestatClient = entry[DATA_CLIENT]
        live = entry[DATA_LIVE]

        thermostats = (live.data.thermostats if live.data else None) or {}
        sensors = (live.data.sensors if live.data else None) or {}

        for tid_str, thermostat in thermostats.items():
            tid = int(tid_str)
            if thermostat_id_filter is not None and tid != thermostat_id_filter:
                continue
            try:
                await _backfill_thermostat(hass, client, tid, thermostat, start, end)
            except BeestatError as err:
                _LOGGER.error(
                    "Backfill failed for thermostat %s: %s", tid, err
                )

        for sid_str, sensor in sensors.items():
            if thermostat_id_filter is not None and int(
                sensor.get("thermostat_id", -1)
            ) != thermostat_id_filter:
                continue
            try:
                await _backfill_sensor(hass, client, int(sid_str), sensor, start, end)
            except BeestatError as err:
                _LOGGER.error("Backfill failed for sensor %s: %s", sid_str, err)


def _chunk_ranges(
    start: datetime, end: datetime
) -> list[tuple[datetime, datetime]]:
    """Split [start, end] into <= 31-day chunks (oldest first)."""
    span = timedelta(days=RUNTIME_MAX_RANGE_DAYS)
    chunks: list[tuple[datetime, datetime]] = []
    cursor = start
    while cursor < end:
        nxt = min(cursor + span, end)
        chunks.append((cursor, nxt))
        cursor = nxt
    return chunks


async def _fetch_runtime_thermostat(
    client: BeestatClient, thermostat_id: int, start: datetime, end: datetime
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for chunk_start, chunk_end in _chunk_ranges(start, end):
        rows.extend(
            await client.runtime_thermostat(
                thermostat_id, chunk_start.isoformat(), chunk_end.isoformat()
            )
        )
    return rows


async def _fetch_runtime_sensor(
    client: BeestatClient, sensor_id: int, start: datetime, end: datetime
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for chunk_start, chunk_end in _chunk_ranges(start, end):
        rows.extend(
            await client.runtime_sensor(
                sensor_id, chunk_start.isoformat(), chunk_end.isoformat()
            )
        )
    return rows


def _hour_floor(ts: datetime) -> datetime:
    return ts.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _parse_ts(value: str) -> datetime:
    # beestat returns ISO 8601 like "2024-01-01T12:30:00+00:00"
    return datetime.fromisoformat(value)


def _temp_unit(thermostat: dict[str, Any]) -> str:
    raw = thermostat.get("temperature_unit") or "°F"
    return "°C" if "C" in raw else "°F"


async def _backfill_thermostat(
    hass: HomeAssistant,
    client: BeestatClient,
    thermostat_id: int,
    thermostat: dict[str, Any],
    start: datetime,
    end: datetime,
) -> None:
    rows = await _fetch_runtime_thermostat(client, thermostat_id, start, end)
    if not rows:
        return

    unit = _temp_unit(thermostat)
    name = thermostat.get("name") or f"Thermostat {thermostat_id}"

    # hour -> {field: list[float]} for means; runtime fields hold seconds
    buckets: dict[datetime, dict[str, list[float]]] = {}
    runtime_buckets: dict[datetime, dict[str, float]] = {}

    for row in rows:
        ts_str = row.get("timestamp")
        if not ts_str:
            continue
        try:
            ts = _parse_ts(ts_str)
        except ValueError:
            continue
        hour = _hour_floor(ts)
        b = buckets.setdefault(hour, {"indoor": [], "outdoor": []})
        rb = runtime_buckets.setdefault(
            hour,
            {"heat": 0.0, "cool": 0.0, "aux_heat": 0.0, "fan": 0.0},
        )

        if (v := row.get("indoor_temperature")) is not None:
            b["indoor"].append(float(v))
        if (v := row.get("outdoor_temperature")) is not None:
            b["outdoor"].append(float(v))

        comp = float(row.get("compressor_1") or 0) + float(row.get("compressor_2") or 0)
        mode = row.get("compressor_mode")
        if mode == "heat":
            rb["heat"] += comp
        elif mode == "cool":
            rb["cool"] += comp

        rb["aux_heat"] += float(row.get("auxiliary_heat_1") or 0) + float(
            row.get("auxiliary_heat_2") or 0
        )
        rb["fan"] += float(row.get("fan") or 0)

    hours = sorted(buckets)

    def _push_mean(stat_id: str, friendly: str, key: str, unit_str: str) -> None:
        records = []
        for h in hours:
            vals = buckets[h][key]
            if not vals:
                continue
            records.append(
                {
                    "start": h,
                    "mean": sum(vals) / len(vals),
                    "min": min(vals),
                    "max": max(vals),
                }
            )
        if records:
            async_add_external_statistics(
                hass,
                {
                    "has_mean": True,
                    "has_sum": False,
                    "name": friendly,
                    "source": DOMAIN,
                    "statistic_id": stat_id,
                    "unit_of_measurement": unit_str,
                },
                records,
            )

    def _push_sum_minutes(stat_id: str, friendly: str, field: str) -> None:
        records = []
        running = 0.0
        for h in hours:
            seconds = runtime_buckets[h][field]
            running += seconds / 60.0
            records.append(
                {
                    "start": h,
                    "sum": round(running, 3),
                    "state": round(seconds / 60.0, 3),
                }
            )
        if records:
            async_add_external_statistics(
                hass,
                {
                    "has_mean": False,
                    "has_sum": True,
                    "name": friendly,
                    "source": DOMAIN,
                    "statistic_id": stat_id,
                    "unit_of_measurement": "min",
                },
                records,
            )

    base = f"{DOMAIN}:thermostat_{thermostat_id}"
    _push_mean(f"{base}_indoor_temperature", f"{name} indoor temperature", "indoor", unit)
    _push_mean(
        f"{base}_outdoor_temperature", f"{name} outdoor temperature", "outdoor", unit
    )
    _push_sum_minutes(f"{base}_heat_runtime", f"{name} heat runtime", "heat")
    _push_sum_minutes(f"{base}_cool_runtime", f"{name} cool runtime", "cool")
    _push_sum_minutes(
        f"{base}_aux_heat_runtime", f"{name} aux heat runtime", "aux_heat"
    )
    _push_sum_minutes(f"{base}_fan_runtime", f"{name} fan runtime", "fan")

    _LOGGER.info(
        "Backfilled %d hourly buckets for thermostat %s (%s)",
        len(hours),
        thermostat_id,
        name,
    )


async def _backfill_sensor(
    hass: HomeAssistant,
    client: BeestatClient,
    sensor_id: int,
    sensor: dict[str, Any],
    start: datetime,
    end: datetime,
) -> None:
    rows = await _fetch_runtime_sensor(client, sensor_id, start, end)
    if not rows:
        return

    name = sensor.get("name") or f"Sensor {sensor_id}"

    buckets: dict[datetime, dict[str, list[float]]] = {}
    for row in rows:
        ts_str = row.get("timestamp")
        if not ts_str:
            continue
        try:
            ts = _parse_ts(ts_str)
        except ValueError:
            continue
        hour = _hour_floor(ts)
        b = buckets.setdefault(hour, {"temperature": [], "occupancy": []})
        if (v := row.get("temperature")) is not None:
            b["temperature"].append(float(v))
        if (v := row.get("occupancy")) is not None:
            b["occupancy"].append(float(v))

    hours = sorted(buckets)
    if not hours:
        return

    temp_records = []
    occ_records = []
    for h in hours:
        temps = buckets[h]["temperature"]
        if temps:
            temp_records.append(
                {
                    "start": h,
                    "mean": sum(temps) / len(temps),
                    "min": min(temps),
                    "max": max(temps),
                }
            )
        occs = buckets[h]["occupancy"]
        if occs:
            occ_records.append(
                {"start": h, "mean": sum(occs) / len(occs) * 100.0}
            )

    base = f"{DOMAIN}:sensor_{sensor_id}"

    # We don't have the parent thermostat's unit handy from the sensor row
    # itself; default to the integration's stated unit on the sensor when
    # present (it isn't, in practice), else °F (beestat US default).
    unit = "°F"

    if temp_records:
        async_add_external_statistics(
            hass,
            {
                "has_mean": True,
                "has_sum": False,
                "name": f"{name} temperature",
                "source": DOMAIN,
                "statistic_id": f"{base}_temperature",
                "unit_of_measurement": unit,
            },
            temp_records,
        )

    if occ_records:
        async_add_external_statistics(
            hass,
            {
                "has_mean": True,
                "has_sum": False,
                "name": f"{name} occupancy",
                "source": DOMAIN,
                "statistic_id": f"{base}_occupancy_pct",
                "unit_of_measurement": "%",
            },
            occ_records,
        )

    _LOGGER.info(
        "Backfilled %d hourly buckets for sensor %s (%s)",
        len(hours),
        sensor_id,
        name,
    )


def async_register_services(hass: HomeAssistant) -> None:
    """Register integration-wide services. Idempotent."""
    if hass.services.has_service(DOMAIN, SERVICE_REFRESH):
        return

    hass.services.async_register(DOMAIN, SERVICE_REFRESH, _do_refresh)
    hass.services.async_register(
        DOMAIN, SERVICE_BACKFILL_HISTORY, _do_backfill, schema=BACKFILL_SCHEMA
    )


def async_unregister_services(hass: HomeAssistant) -> None:
    """Tear down services when the last entry is unloaded."""
    hass.services.async_remove(DOMAIN, SERVICE_REFRESH)
    hass.services.async_remove(DOMAIN, SERVICE_BACKFILL_HISTORY)
