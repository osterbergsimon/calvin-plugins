"""Chromecast Now Playing service plugin.

Discovers Chromecasts on the local network via mDNS and exposes the active
media status (title, artist, album art, app name) as a dashboard widget.
Works with YouTube Music, Spotify, Netflix, Plex, and any Cast-enabled app.

Plugin contract 1.0: one declarative class, config declared once in
`metadata.instance_config_schema`, and `fetch()` as the single data verb.
The display is a `web-component` — the host loads `frontend/dist.js`
(served at /api/plugins/{id}/static/dist.js), mounts the
`calvin-chromecast-now-playing` custom element, and pushes each fetch()
payload onto its `data` property.
"""

import asyncio
import time
from typing import Any

from app.plugins.definitions import PluginMetadata
from app.plugins.protocols import ServicePlugin

try:
    import pychromecast

    _PYCHROMECAST_AVAILABLE = True
except ImportError:
    _PYCHROMECAST_AVAILABLE = False


class ChromecastServicePlugin(ServicePlugin):
    """Displays what is currently casting on a Chromecast device."""

    metadata = PluginMetadata(
        type_id="chromecast",
        name="Chromecast Now Playing",
        description=(
            "Show what's casting on any Chromecast — YouTube Music, Spotify, Netflix and more"
        ),
        supports_multiple_instances=True,
        instance_label="Device",
        default_instance_name="Chromecast",
        # Same device -> same instance (empty device_name falls back to the
        # generic config-hash id).
        instance_identity=["device_name"],
        instance_config_schema={
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
                "type": "integer",
                "description": "mDNS discovery timeout in seconds",
                "default": 5,
                "ui": {
                    "component": "number",
                    "min": 2,
                    "max": 30,
                    "placeholder": "5",
                },
            },
        },
        ui_actions=[
            {
                "id": "save",
                "type": "save",
                "label": "Save Settings",
                "style": "primary",
                "scope": "instance",
            },
        ],
        display_schema={
            "kind": "web-component",
            "title": "Chromecast",
            "title_path": "$.device_name",
            "panel_variant": "media",
            "element": "calvin-chromecast-now-playing",
            "module": "dist.js",
            "poll_interval_ms": 10 * 1000,
        },
    )

    # Config accessors — values live in self.config (schema-normalized).

    @property
    def device_name(self) -> str:
        return str(self.config.get("device_name") or "").strip()

    @property
    def discovery_timeout(self) -> int:
        return int(self.config.get("discovery_timeout") or 5)

    @classmethod
    async def validate_config(cls, config: dict[str, Any]) -> bool:
        """Require pychromecast and a sane discovery timeout."""
        if not _PYCHROMECAST_AVAILABLE:
            return False
        normalized = cls.normalize_config(config)
        timeout = normalized.get("discovery_timeout")
        if timeout is not None and not (2 <= int(timeout) <= 30):
            return False
        return True

    @classmethod
    async def scan_options(cls, field_key: str) -> dict[str, Any] | None:
        """Discover Chromecast devices for the device_name field."""
        if field_key != "device_name":
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

    async def fetch(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Return the now-playing payload the custom element's `data` binds to.

        Shape (documented alongside the element in frontend/dist.js):
            {"state": "no_devices" | "device_not_found" | "idle" | "error"
                      | "<player state, lowercased>",  # playing / paused / buffering
             "device_name"?, "app_name"?, "app_id"?,
             "title"?, "artist"?, "album"?, "album_art_url"?,
             "duration"?, "current_time"?,
             "error"?, "available_devices"?}
        """
        if not _PYCHROMECAST_AVAILABLE:
            return {"state": "error", "error": "pychromecast is not installed"}

        return await asyncio.get_event_loop().run_in_executor(None, self._get_cast_status)

    def _get_cast_status(self) -> dict[str, Any]:
        """Blocking call — runs in a thread pool via run_in_executor."""
        browser = None
        cast = None
        try:
            chromecasts, browser = pychromecast.get_chromecasts(timeout=self.discovery_timeout)

            if not chromecasts:
                return {"state": "no_devices"}

            cast = self._pick_device(chromecasts)
            if cast is None:
                names = [c.cast_info.friendly_name for c in chromecasts]
                return {"state": "device_not_found", "available_devices": names}

            cast.wait(timeout=self.discovery_timeout)
            cast.media_controller.update_status()
            # Allow the Chromecast session to populate media status before reading it.
            time.sleep(0.5)
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
            return result

        except Exception as e:
            return {"state": "error", "error": str(e)}
        finally:
            if browser is not None:
                try:
                    pychromecast.discovery.stop_discovery(browser)
                except Exception:
                    pass
            if cast is not None:
                try:
                    cast.disconnect()
                except Exception:
                    pass

    def _pick_device(self, chromecasts: list) -> Any | None:
        if not self.device_name:
            return chromecasts[0]
        name_lower = self.device_name.lower()
        return next(
            (c for c in chromecasts if c.cast_info.friendly_name.lower() == name_lower),
            None,
        )
