"""Immich self-hosted photo library image plugin (plugin contract 1.0).

One declarative class: config is declared once in
`metadata.instance_config_schema`, the loader discovers the class, and the
gallery plumbing (auth headers, URL building, protected fetches) comes from
`SelfHostedGalleryImagePlugin`.
"""

import random
from datetime import datetime
from typing import Any

import httpx
from loguru import logger

from app.plugins.definitions import PluginMetadata
from app.plugins.sdk.image import SelfHostedGalleryImagePlugin
from app.plugins.utils.scan_cache import load_scan_cache, save_scan_cache

_SCAN_INTERVAL = 3600  # Refresh once per hour


class ImmichImagePlugin(SelfHostedGalleryImagePlugin):
    """Image plugin that serves photos from a self-hosted Immich instance."""

    sdk_plugin_name = "Immich"
    api_base_path = "/api"
    auth_header_name = "x-api-key"

    metadata = PluginMetadata(
        type_id="immich",
        name="Immich",
        description="Photos from your self-hosted Immich photo library",
        default_instance_name="Immich",
        instance_label="Gallery",
        # Same Immich server -> same instance
        instance_identity=["url"],
        instance_config_schema={
            "url": {
                "type": "string",
                "description": "Base URL of your Immich instance (e.g. https://photos.example.com)",
                "default": "",
                "ui": {
                    "component": "input",
                    "placeholder": "https://photos.example.com",
                    "validation": {"required": True, "type": "url"},
                },
            },
            "api_key": {
                "type": "password",
                "description": "Immich API key (Profile → API Keys)",
                "default": "",
                "ui": {
                    "component": "password",
                    "placeholder": "Enter your Immich API key",
                    "validation": {"required": True},
                },
            },
            "album_id": {
                "type": "string",
                "description": "Album ID to source photos from (leave blank for random photos from the whole library)",
                "default": "",
                "ui": {
                    "component": "input",
                    "placeholder": "Leave blank for random from library",
                },
            },
            "count": {
                "type": "integer",
                "description": "Number of photos to fetch",
                "default": 30,
                "ui": {
                    "component": "number",
                    "placeholder": "30",
                    "validation": {"min": 1, "max": 200},
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
            {
                "id": "test",
                "type": "test",
                "label": "Test Connection",
                "style": "secondary",
                "scope": "instance",
            },
        ],
    )

    # Config accessors — base_url and api_key come from the gallery SDK base;
    # these cover the Immich-specific fields.

    @property
    def album_id(self) -> str:
        return str(self.config.get("album_id") or "").strip()

    @property
    def count(self) -> int:
        return int(self.config.get("count") or 30)

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
        """Require url + api_key (schema) and an http(s) URL scheme."""
        if not await super().validate_config(config):
            return False
        normalized = cls.normalize_config(config)
        url = str(normalized.get("url") or "").strip()
        return url.startswith(("http://", "https://"))

    @classmethod
    async def test_connection(cls, config: dict[str, Any]) -> dict[str, Any] | None:
        """Ping the Immich server with the configured API key."""
        normalized = cls.normalize_config(config)
        url = str(normalized.get("url") or "").rstrip("/")
        api_key = str(normalized.get("api_key") or "").strip()
        if not url or not api_key:
            return {"success": False, "message": "Immich URL and API key are required"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{url}/api/server/ping",
                    headers=cls.build_auth_headers(api_key),
                )
            if response.status_code == 200:
                return {"success": True, "message": "Connected to Immich successfully."}
            return {
                "success": False,
                "message": f"Immich returned HTTP {response.status_code}. Check the URL and API key.",
            }
        except httpx.HTTPError as e:
            return {"success": False, "message": f"Could not connect to {url}: {e}"}

    async def get_images(self) -> list[dict[str, Any]]:
        await self.scan_images()
        return self._images.copy()

    async def get_image(self, image_id: str) -> dict[str, Any] | None:
        await self.scan_images()
        return next((img for img in self._images if img["id"] == image_id), None)

    async def get_image_data(self, image_id: str) -> bytes | None:
        # Strip our "immich-" prefix to get the real Immich asset ID
        asset_id = image_id.removeprefix("immich-")
        return await self.fetch_protected_image_data(
            self.api_url(f"assets/{asset_id}/original")
        )

    async def scan_images(self) -> list[dict[str, Any]]:
        if not self.base_url or not self.api_key:
            return self._images.copy()

        if self._last_scan:
            elapsed = (datetime.now() - self._last_scan).total_seconds()
            if elapsed < _SCAN_INTERVAL:
                return self._images.copy()

        try:
            assets = await self._fetch_assets()
            self._images = [self._to_image_metadata(a) for a in assets if a.get("type") == "IMAGE"]
            self._last_scan = datetime.now()
            save_scan_cache(self.plugin_id, self._images)
        except httpx.HTTPStatusError as e:
            logger.warning(f"[Immich] HTTP {e.response.status_code}: {e}")
        except httpx.HTTPError as e:
            logger.warning(f"[Immich] Request error: {e}")
        except Exception as e:
            logger.exception(f"[Immich] Unexpected error scanning images: {e}")

        return self._images.copy()

    async def _fetch_assets(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if self.album_id:
                response = await client.get(
                    self.api_url(f"albums/{self.album_id}"),
                    headers=self.auth_headers(),
                )
                response.raise_for_status()
                data = response.json()
                assets = data.get("assets", [])
                # Shuffle and limit
                random.shuffle(assets)
                return assets[: self.count]
            else:
                # Use the random endpoint — most efficient for slideshow use
                response = await client.get(
                    self.api_url("assets/random"),
                    params={"count": self.count},
                    headers=self.auth_headers(),
                )
                response.raise_for_status()
                return response.json()

    def _to_image_metadata(self, asset: dict[str, Any]) -> dict[str, Any]:
        asset_id = asset.get("id", "")
        exif = asset.get("exifInfo") or {}
        return {
            "id": f"immich-{asset_id}",
            "filename": asset.get("originalFileName", asset_id),
            "url": self.api_url(f"assets/{asset_id}/thumbnail?size=preview"),
            "raw_url": self.api_url(f"assets/{asset_id}/original"),
            "width": exif.get("exifImageWidth", 0),
            "height": exif.get("exifImageHeight", 0),
            "size": asset.get("fileSize", 0),
            "format": asset.get("originalMimeType", "image/jpeg").split("/")[-1],
            "source": self.plugin_id,
            "title": asset.get("originalFileName", ""),
            "description": asset.get("localDateTime", ""),
            "photographer": exif.get("make", ""),
            "date": asset.get("fileCreatedAt", ""),
        }
