"""Unsplash image plugin (plugin contract 1.0).

One declarative class: config is declared once in
`metadata.instance_config_schema` and the loader discovers the class. This is
a single-instance plugin — one Unsplash feed per dashboard.
"""

from datetime import datetime
from typing import Any

import httpx
from loguru import logger

from app.plugins.definitions import PluginMetadata
from app.plugins.protocols import ImagePlugin
from app.plugins.sdk.image import fetch_image_data
from app.plugins.utils.scan_cache import load_scan_cache, save_scan_cache

_BASE_URL = "https://api.unsplash.com"
_SCAN_INTERVAL = 3600  # Rescan every hour
_VALID_CATEGORIES = ("popular", "latest", "oldest")


class UnsplashImagePlugin(ImagePlugin):
    """Unsplash image plugin for fetching popular photos."""

    metadata = PluginMetadata(
        type_id="unsplash",
        name="Unsplash",
        description="Popular photos from Unsplash. Requires an API key from https://unsplash.com/developers",
        default_instance_name="Unsplash",
        supports_multiple_instances=False,
        fixed_instance_id="unsplash-instance",
        instance_config_schema={
            "api_key": {
                "type": "password",
                "description": "Unsplash API key (required). Get one at https://unsplash.com/developers",
                "default": "",
                "ui": {
                    "component": "password",
                    "placeholder": "Enter your Unsplash API key",
                    "help_text": "Get your free API key at https://unsplash.com/developers",
                    "help_link": "https://unsplash.com/developers",
                    "validation": {"required": True},
                },
            },
            "category": {
                "type": "string",
                "description": "Photo category: popular, latest, or oldest",
                "default": "popular",
                "ui": {
                    "component": "select",
                    "options": [
                        {"value": "popular", "label": "Popular"},
                        {"value": "latest", "label": "Latest"},
                        {"value": "oldest", "label": "Oldest"},
                    ],
                },
            },
            "count": {
                "type": "integer",
                "description": "Number of photos to fetch (1-100)",
                "default": 30,
                "ui": {
                    "component": "number",
                    "placeholder": "30",
                    "validation": {"min": 1, "max": 100},
                },
            },
        },
    )

    def __init__(self, plugin_id: str, name: str, enabled: bool = True):
        super().__init__(plugin_id, name, enabled)
        self.base_url = _BASE_URL
        self._images: list[dict[str, Any]] = []
        self._last_scan: datetime | None = None

    # Config accessors — values live in self.config (schema-normalized).

    @property
    def api_key(self) -> str | None:
        return str(self.config.get("api_key") or "").strip() or None

    @property
    def category(self) -> str:
        return str(self.config.get("category") or "popular")

    @property
    def count(self) -> int:
        return min(int(self.config.get("count") or 30), 100)  # Unsplash API limit

    async def initialize(self) -> None:
        cached_images, cached_time = load_scan_cache(self.plugin_id)
        if cached_images:
            self._images = cached_images
            self._last_scan = cached_time
        await self.scan_images()

    async def configure(self, config: dict[str, Any]) -> None:
        """Apply configuration and force a rescan on next access."""
        await super().configure(config)
        self._last_scan = None

    @classmethod
    async def validate_config(cls, config: dict[str, Any]) -> bool:
        """Require an API key (schema); bound count; restrict category."""
        if not await super().validate_config(config):
            return False
        normalized = cls.normalize_config(config)
        if str(normalized.get("category") or "popular") not in _VALID_CATEGORIES:
            return False
        count = normalized.get("count")
        count = 30 if count is None else int(count)
        return 1 <= count <= 100

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

        image_url = image.get("raw_url") or image.get("url")
        if not image_url:
            return None

        return await fetch_image_data(
            image_url,
            plugin_name="Unsplash",
        )

    async def scan_images(self) -> list[dict[str, Any]]:
        """
        Scan for new/updated images from Unsplash.

        Returns:
            List of image metadata dictionaries
        """
        # Check if we need to rescan (avoid too frequent API calls)
        if self._last_scan:
            time_since_scan = (datetime.now() - self._last_scan).total_seconds()
            if time_since_scan < _SCAN_INTERVAL:
                return self._images.copy()

        try:
            params = {
                "per_page": self.count,
                "order_by": self.category,
            }
            headers = {
                "Accept-Version": "v1",
            }

            if self.api_key:
                headers["Authorization"] = f"Client-ID {self.api_key}"
            else:
                logger.warning(
                    "[Unsplash] Plugin used without API key. Rate limits will apply."
                )

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.base_url}/photos", params=params, headers=headers
                )
                response.raise_for_status()
                photos = response.json()

            # Convert Unsplash photos to our image format
            images = []
            for photo in photos:
                image_id = f"unsplash-{photo['id']}"

                # Use regular size for display, raw for download
                urls = photo.get("urls", {})
                regular_url = urls.get("regular", "")
                raw_url = urls.get("raw", regular_url)

                user = photo.get("user", {})
                photographer = user.get("name", "Unknown")

                images.append({
                    "id": image_id,
                    "filename": f"{photo['id']}.jpg",
                    "path": regular_url,
                    "url": regular_url,
                    "raw_url": raw_url,
                    "width": photo.get("width", 0),
                    "height": photo.get("height", 0),
                    "size": 0,  # Size not available from API
                    "format": "jpg",
                    "source": self.plugin_id,
                    "title": photo.get("description")
                    or photo.get("alt_description")
                    or f"Photo by {photographer}",
                    "photographer": photographer,
                    "photographer_url": user.get("links", {}).get("html", ""),
                    "unsplash_id": photo["id"],
                    "created_at": photo.get("created_at"),
                })

            self._images = images
            self._last_scan = datetime.now()
            save_scan_cache(self.plugin_id, images)
            return images

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                logger.error(
                    "Error: Unsplash API requires authentication. Please provide an API key in plugin settings."  # noqa: E501
                )
            elif e.response.status_code == 403:
                logger.error("[Unsplash] API access forbidden. Check your API key.")
            else:
                logger.warning(
                    f"[Unsplash] HTTP error fetching photos: {e.response.status_code} - {e}"
                )
            return self._images.copy()  # cached images if available
        except httpx.HTTPError as e:
            logger.warning(f"[Unsplash] Request error fetching photos: {e}")
            return self._images.copy()
        except Exception as e:
            logger.exception(f"[Unsplash] Unexpected error scanning images: {e}")
            return self._images.copy()
