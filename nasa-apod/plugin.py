"""NASA Astronomy Picture of the Day (APOD) image plugin."""

from datetime import datetime, timedelta
from typing import Any

import httpx

from app.plugins.base import PluginType
from app.plugins.hooks import hookimpl
from app.plugins.protocols import ImagePlugin
from app.plugins.utils.config import extract_config_value, to_int, to_str
from app.plugins.utils.instance_manager import (
    InstanceManagerConfig,
    handle_plugin_config_update_generic,
)
from app.plugins.utils.scan_cache import load_scan_cache, save_scan_cache

_APOD_URL = "https://api.nasa.gov/planetary/apod"
_DEMO_KEY = "DEMO_KEY"
_SCAN_INTERVAL = 86400  # Refresh once per day


class NasaApodImagePlugin(ImagePlugin):
    """NASA Astronomy Picture of the Day image plugin."""

    @classmethod
    def get_plugin_metadata(cls) -> dict[str, Any]:
        return {
            "type_id": "nasa_apod",
            "plugin_type": PluginType.IMAGE,
            "name": "NASA APOD",
            "description": "Astronomy Picture of the Day from NASA",
            "version": "1.0.0",
            "supports_multiple_instances": False,
            "common_config_schema": {
                "api_key": {
                    "type": "string",
                    "description": "NASA API key (leave blank to use the free DEMO_KEY)",
                    "default": "",
                    "ui": {
                        "component": "text",
                        "placeholder": "Optional — get a free key at api.nasa.gov",
                    },
                },
                "count": {
                    "type": "string",
                    "description": "Number of random APOD images to fetch (1–100)",
                    "default": "20",
                    "ui": {
                        "component": "number",
                        "min": 1,
                        "max": 100,
                        "placeholder": "20",
                    },
                },
            },
            "instance_config_schema": {},
            "plugin_class": cls,
        }

    def __init__(
        self,
        plugin_id: str,
        name: str,
        api_key: str = "",
        count: int = 20,
        enabled: bool = True,
    ):
        super().__init__(plugin_id, name, enabled)
        self.api_key = api_key or _DEMO_KEY
        self.count = count
        self._images: list[dict[str, Any]] = []
        self._last_scan: datetime | None = None

    async def initialize(self) -> None:
        # Restore scan results from disk so a restart doesn't re-hit the API
        cached_images, cached_time = load_scan_cache(self.plugin_id)
        if cached_images:
            self._images = cached_images
            self._last_scan = cached_time
        await self.scan_images()

    async def cleanup(self) -> None:
        pass

    async def get_images(self) -> list[dict[str, Any]]:
        await self.scan_images()
        return self._images.copy()

    async def get_image(self, image_id: str) -> dict[str, Any] | None:
        await self.scan_images()
        return next((img for img in self._images if img["id"] == image_id), None)

    async def get_image_data(self, image_id: str) -> bytes | None:
        image = await self.get_image(image_id)
        if not image:
            return None
        url = image.get("url")
        if not url:
            return None
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            try:
                response = await client.get(url)
                response.raise_for_status()
                return response.content
            except httpx.HTTPError as e:
                print(f"NASA APOD: error fetching image data: {e}")
                return None

    async def scan_images(self) -> list[dict[str, Any]]:
        if self._last_scan:
            elapsed = (datetime.now() - self._last_scan).total_seconds()
            if elapsed < _SCAN_INTERVAL:
                return self._images.copy()

        try:
            params: dict[str, Any] = {
                "api_key": self.api_key,
                "count": self.count,
                "thumbs": "true",  # return video thumbnails where applicable
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(_APOD_URL, params=params)
                response.raise_for_status()
                entries = response.json()

            images: list[dict[str, Any]] = []
            for entry in entries:
                media_type = entry.get("media_type", "image")
                if media_type == "video":
                    display_url = entry.get("thumbnail_url")
                    if not display_url:
                        continue  # skip video entries with no thumbnail
                else:
                    display_url = entry.get("url") or entry.get("hdurl")
                    if not display_url:
                        continue

                date_str = entry.get("date", "")
                image_id = f"apod-{date_str}"

                images.append({
                    "id": image_id,
                    "filename": f"apod-{date_str}.jpg",
                    "url": display_url,
                    "raw_url": entry.get("hdurl") or display_url,
                    "width": 0,
                    "height": 0,
                    "size": 0,
                    "format": "jpg",
                    "source": self.plugin_id,
                    "title": entry.get("title", ""),
                    "description": entry.get("explanation", ""),
                    "photographer": entry.get("copyright", "NASA"),
                    "date": date_str,
                    "media_type": media_type,
                })

            self._images = images
            self._last_scan = datetime.now()
            save_scan_cache(self.plugin_id, images)
            return images

        except httpx.HTTPStatusError as e:
            print(f"NASA APOD: HTTP error {e.response.status_code}: {e}")
            return self._images.copy()
        except httpx.HTTPError as e:
            print(f"NASA APOD: request error: {e}")
            return self._images.copy()
        except Exception as e:
            print(f"NASA APOD: unexpected error: {e}")
            return self._images.copy()

    async def validate_config(self, config: dict[str, Any]) -> bool:
        count = extract_config_value(config, "count", default=20, converter=to_int)
        if not (1 <= count <= 100):
            return False
        api_key = extract_config_value(config, "api_key", default="", converter=to_str) or _DEMO_KEY
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    _APOD_URL, params={"api_key": api_key, "count": 1}
                )
                return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def configure(self, config: dict[str, Any]) -> None:
        await super().configure(config)
        self.api_key = extract_config_value(config, "api_key", default="", converter=to_str) or _DEMO_KEY
        self.count = min(extract_config_value(config, "count", default=20, converter=to_int), 100)
        self._last_scan = None  # force refresh on next access


@hookimpl
def register_plugin_types() -> list[dict[str, Any]]:
    return [NasaApodImagePlugin.get_plugin_metadata()]


@hookimpl
def create_plugin_instance(
    plugin_id: str,
    type_id: str,
    name: str,
    config: dict[str, Any],
) -> NasaApodImagePlugin | None:
    if type_id != "nasa_apod":
        return None
    return NasaApodImagePlugin(
        plugin_id=plugin_id,
        name=name,
        api_key=extract_config_value(config, "api_key", default="", converter=to_str),
        count=extract_config_value(config, "count", default=20, converter=to_int),
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
    if type_id != "nasa_apod":
        return None

    def normalize_config(c: dict[str, Any]) -> dict[str, Any]:
        return {
            "api_key": extract_config_value(c, "api_key", default="", converter=to_str),
            "count": extract_config_value(c, "count", default=20, converter=to_int),
        }

    manager_config = InstanceManagerConfig(
        type_id="nasa_apod",
        single_instance=True,
        instance_id="nasa-apod-instance",
        normalize_config=normalize_config,
        default_instance_name="NASA APOD",
    )

    return await handle_plugin_config_update_generic(
        type_id, config, enabled, db_type, session, manager_config
    )
