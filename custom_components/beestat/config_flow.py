"""Config flow for Beestat."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_API_KEY
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import BeestatAuthError, BeestatClient, BeestatError, BeestatRateLimitError
from .const import DOMAIN

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
                errors["base"] = "invalid_auth"
            except BeestatRateLimitError:
                errors["base"] = "rate_limit"
            except BeestatError:
                errors["base"] = "cannot_connect"
            else:
                if not thermostats:
                    errors["base"] = "no_thermostats"
                else:
                    # Use the API key itself as the unique_id so a re-entry of the
                    # same key abort-replaces the existing entry instead of duplicating.
                    await self.async_set_unique_id(api_key)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title="Beestat",
                        data={CONF_API_KEY: api_key},
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=USER_SCHEMA,
            errors=errors,
        )
