"""Config flow for Beestat."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_API_KEY
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import BeestatAuthError, BeestatClient, BeestatError, BeestatRateLimitError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema({vol.Required(CONF_API_KEY): str})


class BeestatConfigFlow(ConfigFlow, domain=DOMAIN):
    """Single-step API key entry."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            session = async_get_clientsession(self.hass)
            client = BeestatClient(session, api_key)

            try:
                thermostats = await client.thermostats()
            except BeestatAuthError:
                _LOGGER.info("Config flow: API key rejected by beestat")
                errors["base"] = "invalid_auth"
            except BeestatRateLimitError:
                _LOGGER.warning("Config flow: rate-limited during validation")
                errors["base"] = "rate_limit"
            except BeestatError as err:
                _LOGGER.warning("Config flow: connection error during validation: %s", err)
                errors["base"] = "cannot_connect"
            else:
                if not thermostats:
                    _LOGGER.info("Config flow: API key valid but no thermostats found")
                    errors["base"] = "no_thermostats"
                else:
                    # Use the API key itself as the unique_id so a re-entry of the
                    # same key abort-replaces the existing entry instead of duplicating.
                    await self.async_set_unique_id(api_key)
                    self._abort_if_unique_id_configured()
                    _LOGGER.info(
                        "Config flow: validated API key; %d thermostat(s) discovered",
                        len(thermostats),
                    )
                    return self.async_create_entry(
                        title="Beestat",
                        data={CONF_API_KEY: api_key},
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=USER_SCHEMA,
            errors=errors,
        )
