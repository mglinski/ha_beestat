"""Data update coordinators for Beestat."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import BeestatAuthError, BeestatClient, BeestatError
from .const import (
    DOMAIN,
    LIVE_SCAN_INTERVAL,
    SUMMARY_LOOKBACK_DAYS,
    SUMMARY_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class LiveData:
    """Snapshot returned from the live coordinator."""

    thermostats: dict[str, dict[str, Any]]
    sensors: dict[str, dict[str, Any]]


class BeestatLiveCoordinator(DataUpdateCoordinator[LiveData]):
    """Polls thermostat.read_id and sensor.read_id every few minutes."""

    def __init__(self, hass: HomeAssistant, client: BeestatClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} live",
            update_interval=LIVE_SCAN_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> LiveData:
        try:
            thermostats = await self.client.thermostats()
            sensors = await self.client.sensors()
        except BeestatAuthError as err:
            # Surfacing as UpdateFailed is enough; auth errors during polling
            # don't get a reauth flow in v1.
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except BeestatError as err:
            raise UpdateFailed(str(err)) from err

        return LiveData(thermostats=thermostats, sensors=sensors)


class BeestatSummaryCoordinator(DataUpdateCoordinator[dict[str, list[dict[str, Any]]]]):
    """Polls runtime_thermostat_summary hourly.

    Returns a dict keyed by thermostat_id (str) containing the list of recent
    daily-summary rows for that thermostat, ordered by date ascending.
    """

    def __init__(self, hass: HomeAssistant, client: BeestatClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} summary",
            update_interval=SUMMARY_SCAN_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, list[dict[str, Any]]]:
        try:
            rows = await self.client.runtime_thermostat_summary()
        except BeestatError as err:
            raise UpdateFailed(str(err)) from err

        # Group by thermostat_id and keep only the last N days.
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            tid = str(row.get("thermostat_id"))
            grouped.setdefault(tid, []).append(row)

        for tid, items in grouped.items():
            items.sort(key=lambda r: r.get("date", ""))
            # `date` is ISO YYYY-MM-DD so lexical sort = chronological.
            grouped[tid] = items[-SUMMARY_LOOKBACK_DAYS:]

        return grouped
