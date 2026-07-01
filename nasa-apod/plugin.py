"""NASA Astronomy Picture of the Day (APOD) image plugin (plugin contract 1.0).

One declarative class: config is declared once in
`metadata.instance_config_schema` and the loader discovers the class. This is
a single-instance plugin — there is exactly one APOD feed.
"""

from datetime import datetime
from typing import Any

import httpx
from loguru import logger

from app.plugins.definitions import PluginMetadata
from app.plugins.protocols import ImagePlugin
from app.plugins.sdk.image import fetch_image_data
from app.plugins.utils.scan_cache import load_scan_cache, save_scan_cache

_APOD_URL = "https://api.nasa.gov/planetary/apod"
_DEMO_KEY = "DEMO_KEY"
_SCAN_INTERVAL = 86400  # Refresh once per day


class NasaApodImagePlugin(ImagePlugin):
    """NASA Astronomy Picture of the Day image plugin."""

    metadata = PluginMetadata(
        type_id="nasa_apod",
        name="NASA APOD",
        description="Astronomy Picture of the Day from NASA",
        default_instance_name="NASA APOD",
        supports_multiple_instances=False,
        fixed_instance_id="nasa-apod-instance",
        instance_config_schema={
            "api_key": {
                "type": "string",
                "description": "NASA API key (leave blank to use the free DEMO_KEY)",
                "default": "",
                "ui": {
                    "component": "input",
                    "placeholder": "Optional — get a free key at api.nasa.gov",
                },
            },
            "count": {
                "type": "integer",
                "description": "Number of random APOD images to fetch (1–100)",
                "default": 20,
                "ui": {
                    "component": "number",
                    "placeholder": "20",
                    "validation": {"min": 1, "max": 100},
                },
            },
        },
    )

    def __init__(self, plugin_id: str, name: str, enabled: bool = True):
        super().__init__(plugin_id, name, enabled)
        self._images: list[dict[str, Any]] = []
        self._last_scan: datetime | None = None

    # Config accessors — values live in self.config (schema-normalized).

    @property
    def api_key(self) -> str:
        return str(self.config.get("api_key") or "").strip() or _DEMO_KEY

    @property
    def count(self) -> int:
        return min(int(self.config.get("count") or 20), 100)

    async def initialize(self) -> None:
        # Restore scan results from disk so a restart doesn't re-hit the API
        cached_images, cached_time = load_scan_cache(self.plugin_id)
        if cached_images:
            self._images = cached_images
            self._last_scan = cached_time
        await self.scan_images()

    async def configure(self, config: dict[str, Any]) -> None:
        """Apply configuration and force a refresh on next access."""
        await super().configure(config)
        self._last_scan = None

    @classmethod
    async def validate_config(cls, config: dict[str, Any]) -> bool:
        """Bound count; the API key is optional (DEMO_KEY fallback)."""
        normalized = cls.normalize_config(config)
        count = normalized.get("count")
        count = 20 if count is None else int(count)
        return 1 <= count <= 100

    @classmethod
    async def test_connection(cls, config: dict[str, Any]) -> dict[str, Any] | None:
        """Fetch one APOD entry with the configured (or demo) API key."""
        normalized = cls.normalize_config(config)
        api_key = str(normalized.get("api_key") or "").strip() or _DEMO_KEY
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(_APOD_URL, params={"api_key": api_key, "count": 1})
            if response.status_code == 200:
                return {"success": True, "message": "Connected to the NASA APOD API."}
            return {
                "success": False,
                "message": f"NASA APOD API returned HTTP {response.status_code}. Check the API key.",
            }
        except httpx.HTTPError as e:
            return {"success": False, "message": f"Could not reach the NASA APOD API: {e}"}

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
        return await fetch_image_data(
            url,
            plugin_name="NASA APOD",
            follow_redirects=True,
        )

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
            logger.warning(f"[NASA APOD] HTTP error {e.response.status_code}: {e}")
            return self._images.copy()
        except httpx.HTTPError as e:
            logger.warning(f"[NASA APOD] Request error: {e}")
            return self._images.copy()
        except Exception as e:
            logger.exception(f"[NASA APOD] Unexpected error scanning images: {e}")
            return self._images.copy()
