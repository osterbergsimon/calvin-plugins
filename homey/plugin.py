"""Homey on/off tiles: switch chosen Homey Pro devices from a Calvin screen.

One declarative class (plugin contract 1.0). The hub address and API key are
used only by `HomeyClient`; nothing here logs config, and every message shown
to a caller is plain words with no key, address or device detail.
"""

import re
from typing import Any

import httpx

from app.plugins.actions import PluginActionError
from app.plugins.definitions import PluginMetadata
from app.plugins.protocols import ServicePlugin
from homey_client import (
    HomeyAuthError,
    HomeyClient,
)

MSG_UNREACHABLE = "Couldn't reach Homey."
MSG_KEY_REFUSED = "Homey refused the API key."


def _clean(config: dict[str, Any]) -> tuple[str, str]:
    """(host without trailing slash, trimmed key) from a normalized config."""
    host = str(config.get("host") or "").strip().rstrip("/")
    key = str(config.get("api_key") or "").strip()
    return host, key


_NETLOC_RE = re.compile(
    r"^(?:[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?|\[[0-9A-Fa-f:.]+\])(?::\d{1,5})?$"
)


def _valid_host(host: str) -> bool:
    """An http(s) address: a host name or IP and optional port, no login, query or fragment."""
    scheme, sep, rest = host.partition("://")
    if scheme not in ("http", "https") or not sep:
        return False
    netloc, _, path = rest.partition("/")
    if not _NETLOC_RE.match(netloc) or any(c in path for c in "?#@ \t\n"):
        return False
    try:
        httpx.URL(host)
    except Exception:  # noqa: BLE001 - never echo the parser's text
        return False
    return True


def _usable(host: str, key: str) -> bool:
    return _valid_host(host) and bool(key)


class HomeyServicePlugin(ServicePlugin):
    """Switch chosen Homey Pro devices on and off."""

    metadata = PluginMetadata(
        type_id="homey",
        name="Homey",
        description="On/off tiles for chosen Homey Pro devices.",
        default_instance_name="Homey",
        instance_label="Homey hub",
        instance_config_schema={
            "host": {
                "type": "string",
                "label": "Hub address",
                "description": (
                    "The address of your Homey Pro on your network, "
                    "for example http://homey.local."
                ),
                "required": True,
                "default": "",
                "ui": {
                    "component": "input",
                    "placeholder": "http://homey.local",
                    "endpoint": True,
                    "validation": {"required": True, "type": "url"},
                },
            },
            "api_key": {
                "type": "password",
                "label": "API key",
                "description": (
                    "In the Homey app: Settings → API Keys. Give the key the scopes "
                    "homey.device.readonly and homey.device.control."
                ),
                "required": True,
                "default": "",
                "ui": {
                    "component": "password",
                    "placeholder": "Enter your Homey API key",
                    "validation": {"required": True},
                },
            },
            "devices": {
                "type": "string",
                "label": "Devices",
                "description": "The devices a tap on this screen can switch.",
                "default": "",
                "ui": {"component": "multi-select-scan"},
            },
        },
        actions=[
            {
                "name": "set_onoff",
                "label": "Switch",
                "params": {
                    "device": {"type": "string"},
                    "on": {"type": "boolean"},
                },
            }
        ],
        ui_actions=[
            {
                "id": "save",
                "type": "save",
                "label": "Save Settings",
                "style": "primary",
                "scope": "instance",
            },
            {
                "id": "test",
                "type": "test",
                "label": "Test Connection",
                "style": "secondary",
                "scope": "instance",
            },
        ],
        display_schema={
            "kind": "switch-grid",
            "data_path": "$.items",
            "poll_interval_ms": 15000,
            "unreachable_text": "Couldn't reach Homey",
            "empty_text": "No devices chosen yet.",
        },
    )

    def __init__(self, plugin_id: str, name: str, enabled: bool = True):
        super().__init__(plugin_id, name, enabled)
        self._client: HomeyClient | None = None

    @property
    def host(self) -> str:
        return _clean(self.config)[0]

    @property
    def api_key(self) -> str:
        return _clean(self.config)[1]

    async def initialize(self) -> None:
        """Validate config and build the hub client."""
        host, key = _clean(self.config)
        if not _valid_host(host):
            raise ValueError(
                "The Homey hub address must be an http:// or https:// address"
            )
        if not key:
            raise ValueError("A Homey API key is required")
        self._client = HomeyClient(host, key)

    async def cleanup(self) -> None:
        await self._close_client()

    async def configure(self, config: dict[str, Any]) -> None:
        """Apply config; drop the client so it is rebuilt with the new key."""
        await super().configure(config)
        await self._close_client()

    async def _close_client(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @classmethod
    async def validate_config(cls, config: dict[str, Any]) -> bool:
        return _usable(*_clean(cls.normalize_config(config)))

    @classmethod
    async def test_connection(cls, config: dict[str, Any]) -> dict[str, Any] | None:
        """One device-list read with the typed (or stored) address and key."""
        host, key = _clean(cls.normalize_config(config))
        if not _usable(host, key):
            return {
                "success": False,
                "message": "Enter a valid hub address and API key.",
            }
        client = None
        try:
            client = HomeyClient(host, key)
            devices = await client.list_devices()
        except HomeyAuthError:
            return {"success": False, "message": MSG_KEY_REFUSED}
        except Exception:  # noqa: BLE001 - shown on screen: fixed words only
            return {"success": False, "message": MSG_UNREACHABLE}
        finally:
            if client is not None:
                await client.aclose()
        return {
            "success": True,
            "message": f"Connected to Homey ({len(devices)} devices).",
        }

    @classmethod
    async def scan_options_with_config(
        cls, field_key: str, config: dict[str, Any]
    ) -> dict[str, Any] | None:
        """List devices that can be switched on and off, as {value, label}."""
        if field_key != "devices":
            return None
        host, key = _clean(cls.normalize_config(config))
        if not _usable(host, key):
            return {"options": [], "error": "Enter the hub address and API key first."}
        client = None
        try:
            client = HomeyClient(host, key)
            devices = await client.list_devices()
        except HomeyAuthError:
            return {"options": [], "error": MSG_KEY_REFUSED}
        except Exception:  # noqa: BLE001 - shown on screen: fixed words only
            return {"options": [], "error": MSG_UNREACHABLE}
        finally:
            if client is not None:
                await client.aclose()
        options = [
            {"value": d.id, "label": f"{d.name} ({d.zone})" if d.zone else d.name}
            for d in devices
            if d.has_onoff
        ]
        options.sort(key=lambda o: (o["label"].casefold(), o["value"]))
        return {"options": options}

    async def perform_action(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        raise PluginActionError("This plugin has no actions.")  # replaced in Task 3.5
