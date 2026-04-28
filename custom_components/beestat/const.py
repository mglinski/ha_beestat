"""Constants for the Beestat integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "beestat"

API_BASE_URL = "https://api.beestat.io/"

# Polling intervals.
LIVE_SCAN_INTERVAL = timedelta(minutes=5)
SUMMARY_SCAN_INTERVAL = timedelta(hours=1)

# How many days of summary data to fetch on each summary refresh.
SUMMARY_LOOKBACK_DAYS = 7

# Beestat caps a single runtime read at 31 days.
RUNTIME_MAX_RANGE_DAYS = 31

# Backfill defaults (when the user calls the service without arguments).
BACKFILL_DEFAULT_DAYS = 30

CONF_API_KEY = "api_key"

# Sub-keys used to slot coordinators into hass.data[DOMAIN][entry_id].
DATA_LIVE = "live"
DATA_SUMMARY = "summary"
DATA_CLIENT = "client"

# Equipment piece names we expect in the live `running_equipment` array.
EQUIPMENT_COMPRESSOR_1 = "compressor_1"
EQUIPMENT_COMPRESSOR_2 = "compressor_2"
EQUIPMENT_AUXILIARY_HEAT_1 = "auxiliary_heat_1"
EQUIPMENT_AUXILIARY_HEAT_2 = "auxiliary_heat_2"
EQUIPMENT_FAN = "fan"
EQUIPMENT_HUMIDIFIER = "humidifier"
EQUIPMENT_DEHUMIDIFIER = "dehumidifier"
EQUIPMENT_VENTILATOR = "ventilator"
EQUIPMENT_ECONOMIZER = "economizer"

# Services
SERVICE_REFRESH = "refresh"
SERVICE_BACKFILL_HISTORY = "backfill_history"
ATTR_DAYS = "days"
ATTR_THERMOSTAT_ID = "thermostat_id"
