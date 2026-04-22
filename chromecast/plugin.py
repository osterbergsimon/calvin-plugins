"""Chromecast Now Playing service plugin.

Discovers Chromecasts on the local network via mDNS and exposes the active
media status (title, artist, album art, app name) as a dashboard widget.
Works with YouTube Music, Spotify, Netflix, Plex, and any Cast-enabled app.
"""

import asyncio
from typing import Any

from app.plugins.base import PluginType
from app.plugins.hooks import hookimpl
from app.plugins.protocols import ServicePlugin
from app.plugins.utils.config import extract_config_value, to_int, to_str
from app.plugins.utils.instance_manager import (
    InstanceManagerConfig,
    handle_plugin_config_update_generic,
)

try:
    import pychromecast
    _PYCHROMECAST_AVAILABLE = True
except ImportError:
    _PYCHROMECAST_AVAILABLE = False


class ChromecastServicePlugin(ServicePlugin):
    """Displays what is currently casting on a Chromecast device."""

    @classmethod
    def get_plugin_metadata(cls) -> dict[str, Any]:
        return {
            "type_id": "chromecast",
            "plugin_type": PluginType.SERVICE,
            "name": "Chromecast Now Playing",
            "description": "Show what's casting on any Chromecast — YouTube Music, Spotify, Netflix and more",
            "version": "1.0.0",
            "supports_multiple_instances": True,
            "instance_label": "Device",
            "common_config_schema": {},
            "instance_config_schema": {
                "device_name": {
                    "type": "string",
                    "description": "Chromecast device",
                    "default": "",
                    "ui": {
                        "component": "select-scan",
                        "placeholder": "Click Scan to discover devices on your network",
                    },
                },
                "discovery_timeout": {
                    "type": "string",
                    "description": "mDNS discovery timeout in seconds",
                    "default": "5",
                    "ui": {
                        "component": "number",
                        "min": 2,
                        "max": 30,
                        "placeholder": "5",
                    },
                },
            },
            "display_schema": {
                "component": "chromecast/NowPlaying.vue",
            },
            "plugin_class": cls,
        }

    def __init__(
        self,
        plugin_id: str,
        name: str,
        device_name: str = "",
        discovery_timeout: int = 5,
        enabled: bool = True,
    ):
        super().__init__(plugin_id, name, enabled)
        self.device_name = device_name
        self.discovery_timeout = discovery_timeout

    async def initialize(self) -> None:
        pass

    async def cleanup(self) -> None:
        pass

    async def get_content(self) -> dict[str, Any]:
        return {
            "type": "chromecast",
            "url": f"/api/web-services/{self.plugin_id}/data",
            "config": {
                "device_name": self.device_name,
            },
        }

    def get_config(self) -> dict[str, Any]:
        return {
            "url": f"/api/web-services/{self.plugin_id}/data",
            "device_name": self.device_name,
        }

    async def fetch_service_data(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        if not _PYCHROMECAST_AVAILABLE:
            return {"error": "pychromecast is not installed"}

        return await asyncio.get_event_loop().run_in_executor(None, self._get_cast_status)

    def _get_cast_status(self) -> dict[str, Any]:
        """Blocking call — runs in a thread pool via run_in_executor."""
        try:
            chromecasts, browser = pychromecast.get_chromecasts(
                timeout=self.discovery_timeout
            )
            pychromecast.discovery.stop_discovery(browser)

            if not chromecasts:
                return {"state": "no_devices"}

            cast = self._pick_device(chromecasts)
            if cast is None:
                names = [c.cast_info.friendly_name for c in chromecasts]
                return {"state": "device_not_found", "available_devices": names}

            cast.wait(timeout=3)
            media = cast.media_controller.status

            result: dict[str, Any] = {
                "device_name": cast.cast_info.friendly_name,
                "app_name": cast.app_display_name or cast.app_id,
                "app_id": cast.app_id,
                "state": "idle",
            }

            if media and media.player_state not in ("IDLE", "UNKNOWN", None):
                result["state"] = media.player_state.lower()
                result["title"] = media.title
                result["artist"] = media.artist
                result["album"] = media.album_name
                result["album_art_url"] = media.images[0].url if media.images else None
                result["duration"] = media.duration
                result["current_time"] = media.current_time

            cast.disconnect()
            return result

        except Exception as e:
            return {"state": "error", "error": str(e)}

    def _pick_device(self, chromecasts: list) -> Any | None:
        if not self.device_name:
            return chromecasts[0]
        name_lower = self.device_name.lower()
        return next(
            (c for c in chromecasts if c.cast_info.friendly_name.lower() == name_lower),
            None,
        )

    async def validate_config(self, config: dict[str, Any]) -> bool:
        if not _PYCHROMECAST_AVAILABLE:
            return False
        return True

    async def configure(self, config: dict[str, Any]) -> None:
        await super().configure(config)
        self.device_name = extract_config_value(config, "device_name", default="", converter=to_str)
        self.discovery_timeout = extract_config_value(config, "discovery_timeout", default=5, converter=to_int)


@hookimpl
async def scan_plugin_options(type_id: str, field_key: str) -> dict[str, Any] | None:
    if type_id != "chromecast" or field_key != "device_name":
        return None
    if not _PYCHROMECAST_AVAILABLE:
        return {"options": [], "error": "pychromecast is not installed"}

    def _discover():
        chromecasts, browser = pychromecast.get_chromecasts(timeout=5)
        pychromecast.discovery.stop_discovery(browser)
        return [
            {"value": c.cast_info.friendly_name, "label": c.cast_info.friendly_name}
            for c in chromecasts
        ]

    options = await asyncio.get_event_loop().run_in_executor(None, _discover)
    return {"options": options}


@hookimpl
def register_plugin_types() -> list[dict[str, Any]]:
    return [ChromecastServicePlugin.get_plugin_metadata()]


@hookimpl
def create_plugin_instance(
    plugin_id: str,
    type_id: str,
    name: str,
    config: dict[str, Any],
) -> ChromecastServicePlugin | None:
    if type_id != "chromecast":
        return None
    return ChromecastServicePlugin(
        plugin_id=plugin_id,
        name=name,
        device_name=extract_config_value(config, "device_name", default="", converter=to_str),
        discovery_timeout=extract_config_value(config, "discovery_timeout", default=5, converter=to_int),
        enabled=config.get("enabled", False),
    )


@hookimpl
async def handle_plugin_config_update(
    type_id: str,
    config: dict[str, Any],
    enabled: bool | None,
    db_type: Any,
    session: Any,
) -> dict[str, Any] | None:
    if type_id != "chromecast":
        return None

    def normalize_config(c: dict[str, Any]) -> dict[str, Any]:
        return {
            "device_name": extract_config_value(c, "device_name", default="", converter=to_str),
            "discovery_timeout": extract_config_value(c, "discovery_timeout", default=5, converter=to_int),
        }

    manager_config = InstanceManagerConfig(
        type_id="chromecast",
        single_instance=False,
        normalize_config=normalize_config,
        default_instance_name="Chromecast",
    )

    return await handle_plugin_config_update_generic(
        type_id, config, enabled, db_type, session, manager_config
    )
