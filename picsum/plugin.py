"""Picsum Photos image plugin (plugin contract 1.0, no API key required).

One declarative class: config is declared once in
`metadata.instance_config_schema` and the loader discovers the class. This is
a single-instance plugin — one random-photo feed.
"""

import random
from datetime import datetime
from typing import Any

import httpx
from loguru import logger

from app.plugins.definitions import PluginMetadata
from app.plugins.protocols import ImagePlugin
from app.plugins.sdk.image import fetch_image_data
from app.plugins.utils.scan_cache import load_scan_cache, save_scan_cache

_BASE_URL = "https://picsum.photos"
_SCAN_INTERVAL = 3600  # Rescan every hour


class PicsumImagePlugin(ImagePlugin):
    """Picsum Photos image plugin for fetching random images without API key."""

    metadata = PluginMetadata(
        type_id="picsum",
        name="Picsum Photos",
        description="Random high-quality images from Picsum Photos (no API key required)",
        default_instance_name="Picsum Photos",
        supports_multiple_instances=False,
        fixed_instance_id="picsum-instance",
        instance_config_schema={
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
    def count(self) -> int:
        return min(int(self.config.get("count") or 30), 100)  # Picsum API limit

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
        """Count must stay within the Picsum API limit (1-100)."""
        normalized = cls.normalize_config(config)
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

        image_url = image.get("url") or image.get("raw_url")
        if not image_url:
            return None

        return await fetch_image_data(
            image_url,
            plugin_name="Picsum",
        )

    async def scan_images(self) -> list[dict[str, Any]]:
        """
        Scan for new/updated images from Picsum Photos.

        Returns:
            List of image metadata dictionaries
        """
        # Check if we need to rescan (avoid too frequent API calls)
        if self._last_scan:
            time_since_scan = (datetime.now() - self._last_scan).total_seconds()
            if time_since_scan < _SCAN_INTERVAL:
                return self._images.copy()

        try:
            # The Picsum /v2/list endpoint doesn't support randomization, so:
            # fetch a random page, shuffle client-side, take the requested count.
            max_page = 10  # Picsum has ~1000 images at ~100 per page
            random_page = random.randint(1, max_page)

            # Fetch more than needed to have enough for shuffling
            fetch_limit = min(max(self.count * 2, 50), 100)  # Picsum API limit is 100 per page

            params = {
                "page": random_page,
                "limit": fetch_limit,
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(f"{self.base_url}/v2/list", params=params)
                response.raise_for_status()
                photos = response.json()

            # Shuffle the photos to randomize the selection
            random.shuffle(photos)
            photos = photos[: self.count]

            # Convert Picsum photos to our image format
            images = []
            for photo in photos:
                image_id = f"picsum-{photo['id']}"

                # Picsum serves images at arbitrary sizes: regular for display,
                # full HD for download.
                regular_url = f"{self.base_url}/id/{photo['id']}/800/600"
                raw_url = f"{self.base_url}/id/{photo['id']}/1920/1080"

                author = photo.get("author", "Unknown")

                images.append({
                    "id": image_id,
                    "filename": f"{photo['id']}.jpg",
                    "path": regular_url,
                    "url": regular_url,
                    "raw_url": raw_url,
                    "width": photo.get("width", 1920),
                    "height": photo.get("height", 1080),
                    "size": 0,  # Size not available from API
                    "format": "jpg",
                    "source": self.plugin_id,
                    "title": f"Photo by {author}",
                    "photographer": author,
                    "photographer_url": photo.get("author_url", ""),
                    "picsum_id": photo["id"],
                    "created_at": photo.get(
                        "download_url", ""
                    ),  # Picsum doesn't provide created_at
                })

            self._images = images
            self._last_scan = datetime.now()
            save_scan_cache(self.plugin_id, images)
            return images

        except httpx.HTTPStatusError as e:
            logger.warning(
                f"[Picsum] HTTP error fetching photos: {e.response.status_code} - {e}"
            )
            return self._images.copy()  # cached images if available
        except httpx.HTTPError as e:
            logger.warning(f"[Picsum] Request error fetching photos: {e}")
            return self._images.copy()
        except Exception as e:
            logger.exception(f"[Picsum] Unexpected error scanning images: {e}")
            return self._images.copy()
