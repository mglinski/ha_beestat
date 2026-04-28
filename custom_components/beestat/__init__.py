"""The Beestat integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import BeestatClient
from .const import DATA_CLIENT, DATA_LIVE, DATA_SUMMARY, DOMAIN
from .coordinator import BeestatLiveCoordinator, BeestatSummaryCoordinator
from .services import async_register_services, async_unregister_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Beestat from a config entry."""
    session = async_get_clientsession(hass)
    client = BeestatClient(session, entry.data[CONF_API_KEY])

    live = BeestatLiveCoordinator(hass, client)
    summary = BeestatSummaryCoordinator(hass, client)

    # First refresh blocks setup so platforms can read data immediately. We
    # only require the live one to succeed; the summary is best-effort because
    # a brand-new beestat account may not have summary rows yet.
    await live.async_config_entry_first_refresh()
    await summary.async_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        DATA_CLIENT: client,
        DATA_LIVE: live,
        DATA_SUMMARY: summary,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            async_unregister_services(hass)
            hass.data.pop(DOMAIN, None)
    return unload_ok
