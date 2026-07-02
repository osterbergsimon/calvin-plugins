"""Lychee self-hosted photo gallery image plugin (plugin contract 1.0).

One declarative class: config is declared once in
`metadata.instance_config_schema`, the loader discovers the class, and the
gallery plumbing (auth headers, URL building, protected fetches) comes from
`SelfHostedGalleryImagePlugin`.
"""

from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import httpx
from loguru import logger

from app.plugins.definitions import PluginMetadata
from app.plugins.sdk.image import SelfHostedGalleryImagePlugin
from app.plugins.utils.scan_cache import load_scan_cache, save_scan_cache

_SCAN_INTERVAL = 3600  # Re-fetch album listing every hour


class LycheeImagePlugin(SelfHostedGalleryImagePlugin):
    """Image plugin that serves photos from a Lychee gallery instance."""

    sdk_plugin_name = "Lychee"
    api_base_path = "/api/v2"
    auth_header_name = "Authorization"
    auth_header_prefix = "Bearer "

    metadata = PluginMetadata(
        type_id="lychee",
        name="Lychee",
        description="Photos from your self-hosted Lychee photo gallery",
        default_instance_name="Lychee",
        instance_label="Gallery",
        # Same Lychee server -> same instance
        instance_identity=["url"],
        instance_config_schema={
            "url": {
                "type": "string",
                "description": "Base URL of your Lychee instance (e.g. https://photos.example.com)",
                "default": "",
                "ui": {
                    "component": "input",
                    "placeholder": "https://photos.example.com",
                    "validation": {"required": True, "type": "url"},
                },
            },
            "api_key": {
                "type": "password",
                "description": "Lychee API token (Settings → Security → API keys)",
                "default": "",
                "ui": {
                    "component": "password",
                    "placeholder": "Enter your Lychee API token",
                    "validation": {"required": True},
                },
            },
            "album_id": {
                "type": "string",
                "description": "Album ID to show (leave blank for all accessible photos)",
                "default": "",
                "ui": {
                    "component": "input",
                    "placeholder": "Leave blank for all albums",
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
    # this covers the Lychee-specific field.

    @property
    def album_id(self) -> str:
        return str(self.config.get("album_id") or "").strip()

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
        """List Lychee albums with the configured API token."""
        normalized = cls.normalize_config(config)
        url = str(normalized.get("url") or "").rstrip("/")
        api_key = str(normalized.get("api_key") or "").strip()
        if not url or not api_key:
            return {"success": False, "message": "Lychee URL and API token are required"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{url}/api/v2/Albums",
                    headers=cls.build_auth_headers(api_key),
                )
            if response.status_code == 200:
                return {"success": True, "message": "Connected to Lychee successfully."}
            return {
                "success": False,
                "message": f"Lychee returned HTTP {response.status_code}. Check the URL and API token.",
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
        image = await self.get_image(image_id)
        if not image:
            return None
        url = image.get("url")
        if not url:
            return None
        return await self.fetch_protected_image_data(url)

    async def scan_images(self) -> list[dict[str, Any]]:
        if not self.base_url or not self.api_key:
            return self._images.copy()

        if self._last_scan:
            elapsed = (datetime.now() - self._last_scan).total_seconds()
            if elapsed < _SCAN_INTERVAL:
                return self._images.copy()

        try:
            photos = await self._fetch_photos()
            self._images = [self._to_image_metadata(p) for p in photos]
            self._last_scan = datetime.now()
            save_scan_cache(self.plugin_id, self._images)
        except httpx.HTTPStatusError as e:
            logger.warning(f"[Lychee] HTTP {e.response.status_code}: {e}")
        except httpx.HTTPError as e:
            logger.warning(f"[Lychee] Request error: {e}")
        except Exception as e:
            logger.exception(f"[Lychee] Unexpected error scanning images: {e}")

        return self._images.copy()

    async def _fetch_photos(self) -> list[dict[str, Any]]:
        """Fetch photo list from Lychee, optionally filtered by album."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            if self.album_id:
                response = await client.post(
                    self.api_url("Album"),
                    json={"albumID": self.album_id},
                    headers=self.auth_headers(),
                )
                response.raise_for_status()
                data = response.json()
                return data.get("photos", [])
            else:
                # Fetch root albums then collect photos from each
                response = await client.post(
                    self.api_url("Albums"),
                    headers=self.auth_headers(),
                )
                response.raise_for_status()
                data = response.json()
                albums = data.get("albums", []) or []

                photos: list[dict[str, Any]] = []
                for album in albums:
                    album_id = album.get("id")
                    if not album_id:
                        continue
                    album_resp = await client.post(
                        self.api_url("Album"),
                        json={"albumID": album_id},
                        headers=self.auth_headers(),
                    )
                    if album_resp.status_code == 200:
                        album_data = album_resp.json()
                        photos.extend(album_data.get("photos", []))
                return photos

    def _to_image_metadata(self, photo: dict[str, Any]) -> dict[str, Any]:
        photo_id = photo.get("id", "")
        size_variants = photo.get("size_variants", {}) or {}
        original = size_variants.get("original") or {}
        medium = size_variants.get("medium") or size_variants.get("small") or {}

        display_url = medium.get("url") or original.get("url") or ""
        raw_url = original.get("url") or display_url

        # Lychee URLs may be relative
        if display_url and not display_url.startswith("http"):
            display_url = urljoin(self.base_url + "/", display_url.lstrip("/"))
        if raw_url and not raw_url.startswith("http"):
            raw_url = urljoin(self.base_url + "/", raw_url.lstrip("/"))

        return {
            "id": f"lychee-{photo_id}",
            "filename": photo.get("title", photo_id),
            "url": display_url,
            "raw_url": raw_url,
            "width": original.get("width", 0),
            "height": original.get("height", 0),
            "size": original.get("filesize", 0),
            "format": photo.get("type", "jpg").split("/")[-1],
            "source": self.plugin_id,
            "title": photo.get("title", ""),
            "description": photo.get("description", ""),
            "photographer": photo.get("taken_at", ""),
            "date": photo.get("created_at", ""),
        }
