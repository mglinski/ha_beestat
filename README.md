# Beestat for Home Assistant

A Home Assistant custom integration that consumes data from the [beestat.io](https://beestat.io) REST API and exposes it as sensor and binary_sensor entities.

> **Note:** Despite the repo name, this is a *custom integration* (HACS-installable), not a [Home Assistant Add-on](https://www.home-assistant.io/addons/). Add-ons are containerized services managed by Supervisor; integrations create entities you can use in automations, dashboards, and statistics.

## What you get

For each thermostat:

| Entity | Source |
|---|---|
| Temperature, Humidity, Heat setpoint, Cool setpoint | `thermostat.read_id` (live, every 5 min) |
| Heat / Cool / Aux heat / Fan runtime (latest day) | `runtime_thermostat_summary.read` (every hour) |
| Avg indoor / outdoor temperature (latest day) | `runtime_thermostat_summary.read` |
| Compressor stage 1/2, Heat stage 1/2, Fan binary sensors (only for stages your system has) | `running_equipment` field |

For each remote sensor:

| Entity | Source |
|---|---|
| Temperature (and Humidity if reported) | `sensor.read_id` |
| Occupancy binary sensor | `sensor.read_id` (skipped for sensors that don't report occupancy) |

## Install

### Via HACS (recommended)

1. In HACS → Integrations → ⋮ → **Custom repositories**
2. Add this repo's URL with category **Integration**
3. Install **Beestat**, then restart Home Assistant.

### Manual

Copy `custom_components/beestat/` into your Home Assistant `config/custom_components/` directory and restart.

## Configure

1. **Settings → Devices & Services → Add Integration → Beestat**
2. Paste your beestat API key.

To generate an API key: log in at [beestat.io](https://beestat.io), open **Settings → API key**.

The integration polls the live endpoints every 5 minutes and the daily summary every hour. Beestat itself caches its sync from ecobee at 3-minute intervals, so polling faster than that wouldn't yield fresher data and would chew through your ~30 req/min rate limit.

## Services

### `beestat.refresh`

Force-refresh both the live and summary coordinators.

### `beestat.backfill_history`

Pull 5-minute interval thermostat and remote-sensor history from beestat and import it into Home Assistant **long-term statistics**. Useful right after install so historical charts aren't empty.

| Field | Description |
|---|---|
| `days` | Days back from now (1–365). Default **30**. Beestat caps each call at 31 days; longer ranges are chunked automatically. |
| `thermostat_id` | Optional. Restrict to a single thermostat (and its remote sensors). Omit to backfill everything. |

Statistics IDs created:

- `beestat:thermostat_<id>_indoor_temperature` (mean per hour)
- `beestat:thermostat_<id>_outdoor_temperature` (mean per hour)
- `beestat:thermostat_<id>_heat_runtime` (sum, minutes)
- `beestat:thermostat_<id>_cool_runtime` (sum, minutes)
- `beestat:thermostat_<id>_aux_heat_runtime` (sum, minutes)
- `beestat:thermostat_<id>_fan_runtime` (sum, minutes)
- `beestat:sensor_<id>_temperature` (mean per hour)
- `beestat:sensor_<id>_occupancy_pct` (mean of 0/1 × 100)

Find them in **Developer Tools → Statistics**.

Example call from Developer Tools → Services:

```yaml
service: beestat.backfill_history
data:
  days: 60
```

## Notes & limits

- **Read-only.** This integration does not write to beestat or change setpoints. Use the official ecobee integration for HVAC control.
- **Rate limit ≈ 30 req/min.** Default polling stays well under that. The backfill service can hit it on very long ranges with many sensors; if so, beestat will reject calls and the service will log errors but won't keep retrying.
- **Temperature units** follow whatever your thermostat reports — Home Assistant will display in your preferred unit via its built-in conversion.
- **Climate entity, scores, profile** are not exposed in v1. Open an issue if you want them.

## Troubleshooting

- *"Invalid API key"* — Double-check the key in beestat.io → Settings → API key. Keys are revocable; re-paste the current one.
- *No entities appear* — Make sure your beestat account has at least one thermostat that has fully synced. New accounts can take a few minutes after first connecting ecobee.
- *Stats are empty* — The summary table populates as beestat catches up on history; there can be a delay of a day or two on a fresh account.

## License

MIT
