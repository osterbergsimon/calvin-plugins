"""Immich self-hosted photo library image plugin."""

from datetime import datetime
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

_SCAN_INTERVAL = 3600  # Refresh once per hour


class ImmichImagePlugin(ImagePlugin):
    """Image plugin that serves photos from a self-hosted Immich instance."""

    @classmethod
    def get_plugin_metadata(cls) -> dict[str, Any]:
        return {
            "type_id": "immich",
            "plugin_type": PluginType.IMAGE,
            "name": "Immich",
            "description": "Photos from your self-hosted Immich photo library",
            "version": "1.0.0",
            "supports_multiple_instances": True,
            "instance_label": "Gallery",
            "common_config_schema": {},
            "instance_config_schema": {
                "url": {
                    "type": "string",
                    "description": "Base URL of your Immich instance (e.g. https://photos.example.com)",
                    "default": "",
                    "ui": {
                        "component": "text",
                        "placeholder": "https://photos.example.com",
                        "validation": {"required": True},
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
                        "component": "text",
                        "placeholder": "Leave blank for random from library",
                    },
                },
                "count": {
                    "type": "string",
                    "description": "Number of photos to fetch",
                    "default": "30",
                    "ui": {
                        "component": "number",
                        "min": 1,
                        "max": 200,
                        "placeholder": "30",
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
        count: int = 30,
        enabled: bool = True,
    ):
        super().__init__(plugin_id, name, enabled)
        self.base_url = url.rstrip("/")
        self.api_key = api_key
        self.album_id = album_id
        self.count = count
        self._images: list[dict[str, Any]] = []
        self._last_scan: datetime | None = None

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "Accept": "application/json",
        }

    def _api(self, path: str) -> str:
        return f"{self.base_url}/api/{path.lstrip('/')}"

    async def initialize(self) -> None:
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
        # Strip our "immich-" prefix to get the real Immich asset ID
        asset_id = image_id.removeprefix("immich-")
        url = self._api(f"assets/{asset_id}/original")
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            try:
                response = await client.get(url, headers=self._headers())
                response.raise_for_status()
                return response.content
            except httpx.HTTPError as e:
                print(f"Immich: error fetching image data: {e}")
                return None

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
        except httpx.HTTPStatusError as e:
            print(f"Immich: HTTP {e.response.status_code}: {e}")
        except httpx.HTTPError as e:
            print(f"Immich: request error: {e}")
        except Exception as e:
            print(f"Immich: unexpected error: {e}")

        return self._images.copy()

    async def _fetch_assets(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if self.album_id:
                response = await client.get(
                    self._api(f"albums/{self.album_id}"),
                    headers=self._headers(),
                )
                response.raise_for_status()
                data = response.json()
                assets = data.get("assets", [])
                # Shuffle and limit
                import random
                random.shuffle(assets)
                return assets[: self.count]
            else:
                # Use the random endpoint — most efficient for slideshow use
                response = await client.get(
                    self._api("assets/random"),
                    params={"count": self.count},
                    headers=self._headers(),
                )
                response.raise_for_status()
                return response.json()

    def _to_image_metadata(self, asset: dict[str, Any]) -> dict[str, Any]:
        asset_id = asset.get("id", "")
        exif = asset.get("exifInfo") or {}
        thumbhash = asset.get("thumbhash", "")
        return {
            "id": f"immich-{asset_id}",
            "filename": asset.get("originalFileName", asset_id),
            "url": self._api(f"assets/{asset_id}/thumbnail?size=preview"),
            "raw_url": self._api(f"assets/{asset_id}/original"),
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

    async def validate_config(self, config: dict[str, Any]) -> bool:
        url = extract_config_value(config, "url", default="", converter=to_str).rstrip("/")
        api_key = extract_config_value(config, "api_key", default="", converter=to_str)
        if not url or not api_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{url}/api/server/ping",
                    headers={"x-api-key": api_key, "Accept": "application/json"},
                )
                return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def configure(self, config: dict[str, Any]) -> None:
        await super().configure(config)
        self.base_url = extract_config_value(config, "url", default="", converter=to_str).rstrip("/")
        self.api_key = extract_config_value(config, "api_key", default="", converter=to_str)
        self.album_id = extract_config_value(config, "album_id", default="", converter=to_str)
        self.count = extract_config_value(config, "count", default=30, converter=to_int)
        self._last_scan = None


@hookimpl
def register_plugin_types() -> list[dict[str, Any]]:
    return [ImmichImagePlugin.get_plugin_metadata()]


@hookimpl
def create_plugin_instance(
    plugin_id: str,
    type_id: str,
    name: str,
    config: dict[str, Any],
) -> ImmichImagePlugin | None:
    if type_id != "immich":
        return None
    return ImmichImagePlugin(
        plugin_id=plugin_id,
        name=name,
        url=extract_config_value(config, "url", default="", converter=to_str),
        api_key=extract_config_value(config, "api_key", default="", converter=to_str),
        album_id=extract_config_value(config, "album_id", default="", converter=to_str),
        count=extract_config_value(config, "count", default=30, converter=to_int),
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
    if type_id != "immich":
        return None

    def normalize_config(c: dict[str, Any]) -> dict[str, Any]:
        return {
            "url": extract_config_value(c, "url", default="", converter=to_str),
            "api_key": extract_config_value(c, "api_key", default="", converter=to_str),
            "album_id": extract_config_value(c, "album_id", default="", converter=to_str),
            "count": extract_config_value(c, "count", default=30, converter=to_int),
        }

    manager_config = InstanceManagerConfig(
        type_id="immich",
        single_instance=False,
        normalize_config=normalize_config,
        default_instance_name="Immich",
    )

    return await handle_plugin_config_update_generic(
        type_id, config, enabled, db_type, session, manager_config
    )
