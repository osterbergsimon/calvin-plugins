"""Lychee self-hosted photo gallery image plugin."""

from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import httpx
from loguru import logger

from app.plugins.base import PluginType
from app.plugins.hooks import hookimpl
from app.plugins.protocols import ImagePlugin
from app.plugins.utils.config import extract_config_value, to_str, to_int
from app.plugins.utils.instance_manager import (
    InstanceManagerConfig,
    handle_plugin_config_update_generic,
)
from app.plugins.utils.scan_cache import load_scan_cache, save_scan_cache

_SCAN_INTERVAL = 3600  # Re-fetch album listing every hour


class LycheeImagePlugin(ImagePlugin):
    """Image plugin that serves photos from a Lychee gallery instance."""

    @classmethod
    def get_plugin_metadata(cls) -> dict[str, Any]:
        return {
            "type_id": "lychee",
            "plugin_type": PluginType.IMAGE,
            "name": "Lychee",
            "description": "Photos from your self-hosted Lychee photo gallery",
            "version": "1.0.0",
            "supports_multiple_instances": True,
            "instance_label": "Gallery",
            "common_config_schema": {},
            "instance_config_schema": {
                "url": {
                    "type": "string",
                    "description": "Base URL of your Lychee instance (e.g. https://photos.example.com)",
                    "default": "",
                    "ui": {
                        "component": "text",
                        "placeholder": "https://photos.example.com",
                        "validation": {"required": True},
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
                        "component": "text",
                        "placeholder": "Leave blank for all albums",
                    },
                },
            },
            "plugin_class": cls,
        }

    def __init__(
        self,
        plugin_id: str,
        name: str,
        url: str = "",
        api_key: str = "",
        album_id: str = "",
        enabled: bool = True,
    ):
        super().__init__(plugin_id, name, enabled)
        self.base_url = url.rstrip("/")
        self.api_key = api_key
        self.album_id = album_id
        self._images: list[dict[str, Any]] = []
        self._last_scan: datetime | None = None

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

    def _api(self, path: str) -> str:
        return f"{self.base_url}/api/v2/{path.lstrip('/')}"

    async def initialize(self) -> None:
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
                response = await client.get(url, headers=self._headers())
                response.raise_for_status()
                return response.content
            except httpx.HTTPError as e:
                logger.warning(f"[Lychee] Error fetching image data: {e}")
                return None

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
                    self._api("Album"),
                    json={"albumID": self.album_id},
                    headers=self._headers(),
                )
                response.raise_for_status()
                data = response.json()
                return data.get("photos", [])
            else:
                # Fetch root albums then collect photos from each
                response = await client.post(
                    self._api("Albums"),
                    headers=self._headers(),
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
                        self._api("Album"),
                        json={"albumID": album_id},
                        headers=self._headers(),
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

    async def validate_config(self, config: dict[str, Any]) -> bool:
        url = extract_config_value(config, "url", default="", converter=to_str).rstrip("/")
        api_key = extract_config_value(config, "api_key", default="", converter=to_str)
        if not url or not api_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{url}/api/v2/Albums",
                    headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
                )
                return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def configure(self, config: dict[str, Any]) -> None:
        await super().configure(config)
        self.base_url = extract_config_value(config, "url", default="", converter=to_str).rstrip("/")
        self.api_key = extract_config_value(config, "api_key", default="", converter=to_str)
        self.album_id = extract_config_value(config, "album_id", default="", converter=to_str)
        self._last_scan = None


@hookimpl
def register_plugin_types() -> list[dict[str, Any]]:
    return [LycheeImagePlugin.get_plugin_metadata()]


@hookimpl
def create_plugin_instance(
    plugin_id: str,
    type_id: str,
    name: str,
    config: dict[str, Any],
) -> LycheeImagePlugin | None:
    if type_id != "lychee":
        return None
    return LycheeImagePlugin(
        plugin_id=plugin_id,
        name=name,
        url=extract_config_value(config, "url", default="", converter=to_str),
        api_key=extract_config_value(config, "api_key", default="", converter=to_str),
        album_id=extract_config_value(config, "album_id", default="", converter=to_str),
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
    if type_id != "lychee":
        return None

    def normalize_config(c: dict[str, Any]) -> dict[str, Any]:
        return {
            "url": extract_config_value(c, "url", default="", converter=to_str),
            "api_key": extract_config_value(c, "api_key", default="", converter=to_str),
            "album_id": extract_config_value(c, "album_id", default="", converter=to_str),
        }

    manager_config = InstanceManagerConfig(
        type_id="lychee",
        single_instance=False,
        normalize_config=normalize_config,
        default_instance_name="Lychee",
    )

    return await handle_plugin_config_update_generic(
        type_id, config, enabled, db_type, session, manager_config
    )
