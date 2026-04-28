"""Async client for the Beestat REST API.

Beestat exposes a single endpoint that dispatches by `resource` + `method`
query parameters. All authenticated calls require an `api_key` query param.
Responses are wrapped in `{"success": bool, "data": ...}`. On failure, `data`
contains `error_message` and `error_code`.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp
import async_timeout

from .const import API_BASE_URL

_LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30


class BeestatError(Exception):
    """Base error for Beestat API failures."""


class BeestatAuthError(BeestatError):
    """Raised when the API key is rejected."""


class BeestatRateLimitError(BeestatError):
    """Raised when the rate limit (~30 req/min) is hit."""


class BeestatClient:
    """Thin async wrapper around the Beestat HTTP API."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str) -> None:
        self._session = session
        self._api_key = api_key

    async def _call(
        self,
        resource: str,
        method: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        params = {
            "api_key": self._api_key,
            "resource": resource,
            "method": method,
        }
        if arguments is not None:
            params["arguments"] = json.dumps(arguments, separators=(",", ":"))

        try:
            async with async_timeout.timeout(DEFAULT_TIMEOUT):
                resp = await self._session.get(API_BASE_URL, params=params)
                payload = await resp.json(content_type=None)
        except asyncio.TimeoutError as err:
            raise BeestatError(f"Timeout calling beestat {resource}.{method}") from err
        except aiohttp.ClientError as err:
            raise BeestatError(f"Network error calling beestat: {err}") from err
        except (ValueError, json.JSONDecodeError) as err:
            raise BeestatError(f"Invalid JSON from beestat: {err}") from err

        if not isinstance(payload, dict):
            raise BeestatError(f"Unexpected response shape: {payload!r}")

        if payload.get("success") is True:
            return payload.get("data")

        data = payload.get("data") or {}
        message = data.get("error_message", "unknown error")
        code = data.get("error_code")
        # Beestat returns specific codes for auth/rate; map heuristically by message
        # since the documented set isn't published.
        lowered = str(message).lower()
        if "api key" in lowered or "unauthor" in lowered or code in (1004, 1005):
            raise BeestatAuthError(message)
        if "rate" in lowered or "limit" in lowered or code == 1209:
            raise BeestatRateLimitError(message)
        raise BeestatError(f"Beestat error {code}: {message}")

    async def thermostats(self) -> dict[str, dict[str, Any]]:
        """Return all thermostats keyed by thermostat_id (string)."""
        data = await self._call("thermostat", "read_id")
        return data or {}

    async def sensors(self) -> dict[str, dict[str, Any]]:
        """Return all sensors keyed by sensor_id (string)."""
        data = await self._call("sensor", "read_id")
        return data or {}

    async def runtime_thermostat_summary(
        self, thermostat_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Per-day aggregate runtime data.

        Beestat exposes only `read_id` on this resource (not `read`). `read_id`
        returns a dict keyed by `runtime_thermostat_summary_id`; we flatten to
        a list. The exposed call does NOT divide the *10-stored temperature
        and degree-day fields, so we normalize them client-side here.
        """
        args: dict[str, Any] | None = None
        if thermostat_id is not None:
            args = {"attributes": {"thermostat_id": int(thermostat_id)}}
        data = await self._call(
            "runtime_thermostat_summary", "read_id", args
        )
        if not data:
            return []

        rows = list(data.values()) if isinstance(data, dict) else list(data)

        scale_fields = (
            "avg_outdoor_temperature",
            "min_outdoor_temperature",
            "max_outdoor_temperature",
            "avg_indoor_temperature",
            "sum_heating_degree_days",
            "sum_cooling_degree_days",
        )
        for row in rows:
            for field in scale_fields:
                value = row.get(field)
                if value is not None:
                    row[field] = value / 10
        return rows

    async def runtime_thermostat(
        self,
        thermostat_id: int,
        start: str,
        end: str,
    ) -> list[dict[str, Any]]:
        """5-minute interval thermostat history. Max 31-day window per call.

        Timestamps are ISO 8601 strings (UTC recommended). cora dispatches
        arguments by PHP parameter name via reflection, so filter values must
        be wrapped under `attributes` to match `read($attributes, $columns)`.
        """
        args = {
            "attributes": {
                "thermostat_id": int(thermostat_id),
                "timestamp": {
                    "operator": "between",
                    "value": [start, end],
                },
            }
        }
        data = await self._call("runtime_thermostat", "read", args)
        return data or []

    async def runtime_sensor(
        self,
        sensor_id: int,
        start: str,
        end: str,
    ) -> list[dict[str, Any]]:
        """5-minute interval remote-sensor history. Max 31-day window per call."""
        args = {
            "attributes": {
                "sensor_id": int(sensor_id),
                "timestamp": {
                    "operator": "between",
                    "value": [start, end],
                },
            }
        }
        data = await self._call("runtime_sensor", "read", args)
        return data or []
