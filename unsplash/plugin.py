"""Unsplash image plugin."""

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


class UnsplashImagePlugin(ImagePlugin):
    """Unsplash image plugin for fetching popular photos."""

    @classmethod
    def get_plugin_metadata(cls) -> dict[str, Any]:
        """Get plugin metadata for registration."""
        return {
            "type_id": "unsplash",
            "plugin_type": PluginType.IMAGE,
            "name": "Unsplash",
            "description": "Popular photos from Unsplash. Requires an API key from https://unsplash.com/developers",
            "version": "1.0.0",
            "supports_multiple_instances": False,  # Single-instance plugin
            "common_config_schema": {
                "api_key": {
                    "type": "password",
                    "description": "Unsplash API key (required). Get one at https://unsplash.com/developers",
                    "default": "",
                    "ui": {
                        "component": "password",
                        "placeholder": "Enter your Unsplash API key",
                        "help_text": "Get your free API key at https://unsplash.com/developers",
                        "help_link": "https://unsplash.com/developers",
                        "validation": {
                            "required": True,
                        },
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
                    "type": "string",
                    "description": "Number of photos to fetch (1-100)",
                    "default": "30",
                    "ui": {
                        "component": "number",
                        "min": 1,
                        "max": 100,
                        "placeholder": "30",
                    },
                },
            },
            "instance_config_schema": {},  # No instance-specific settings (single-instance)
            "plugin_class": cls,
        }

    def __init__(
        self,
        plugin_id: str,
        name: str,
        api_key: str | None = None,
        category: str = "popular",
        count: int = 30,
        enabled: bool = True,
    ):
        """
        Initialize Unsplash image plugin.

        Args:
            plugin_id: Unique identifier for the plugin
            name: Human-readable name
            api_key: Unsplash API key (optional for basic usage)
            category: Photo category ('popular', 'latest', 'oldest')
            count: Number of photos to fetch (default: 30)
            enabled: Whether the plugin is enabled
        """
        super().__init__(plugin_id, name, enabled)
        self.api_key = api_key
        self.category = category
        self.count = count
        self.base_url = "https://api.unsplash.com"
        self._images: list[dict[str, Any]] = []
        self._last_scan: datetime | None = None
        self._scan_interval = 3600  # Rescan every hour

    async def initialize(self) -> None:
        """Initialize the plugin."""
        await self.scan_images()

    async def cleanup(self) -> None:
        """Cleanup plugin resources."""
        # Nothing to cleanup for API-based plugin
        pass

    async def get_images(self) -> list[dict[str, Any]]:
        """
        Get list of all available images.

        Returns:
            List of image metadata dictionaries
        """
        await self.scan_images()
        return self._images.copy()

    async def get_image(self, image_id: str) -> dict[str, Any] | None:
        """
        Get image metadata by ID.

        Args:
            image_id: Image identifier (Unsplash photo ID)

        Returns:
            Image metadata dictionary or None if not found
        """
        await self.scan_images()
        return next((img for img in self._images if img["id"] == image_id), None)

    async def get_image_data(self, image_id: str) -> bytes | None:
        """
        Get image file data by ID.

        Args:
            image_id: Image identifier (Unsplash photo ID)

        Returns:
            Image file data as bytes or None if not found
        """
        # Find the image to get its URL
        image = await self.get_image(image_id)
        if not image:
            return None

        # Get the raw image URL
        image_url = image.get("raw_url") or image.get("url")
        if not image_url:
            return None

        # Fetch the image
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(image_url)
                response.raise_for_status()
                return response.content
            except httpx.HTTPError as e:
                print(f"Error fetching image from Unsplash: {e}")
                return None

    async def scan_images(self) -> list[dict[str, Any]]:
        """
        Scan for new/updated images from Unsplash.

        Returns:
            List of image metadata dictionaries
        """
        # Check if we need to rescan (avoid too frequent API calls)
        if self._last_scan:
            time_since_scan = (datetime.now() - self._last_scan).total_seconds()
            if time_since_scan < self._scan_interval:
                return self._images.copy()

        try:
            # Use Unsplash API to get photos
            # For basic usage without API key, we can use the public endpoint
            # But with API key, we get better rate limits
            url = f"{self.base_url}/photos"
            params = {
                "per_page": self.count,
                "order_by": self.category,
            }

            headers = {
                "Accept-Version": "v1",
            }

            # Add API key if provided
            if self.api_key:
                headers["Authorization"] = f"Client-ID {self.api_key}"
            else:
                # Without API key, we'll get rate limited quickly
                # For testing, we can use a demo access key or just handle errors gracefully
                print("Warning: Unsplash plugin used without API key. Rate limits will apply.")
                # Try to use demo access (this may not work without proper setup)
                # In production, users should provide their own API key

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                photos = response.json()

            # Convert Unsplash photos to our image format
            images = []
            for photo in photos:
                # Generate a unique ID from the photo ID
                image_id = f"unsplash-{photo['id']}"

                # Get image URLs (use regular size for display, raw for download)
                urls = photo.get("urls", {})
                regular_url = urls.get("regular", "")
                raw_url = urls.get("raw", regular_url)

                # Get dimensions
                width = photo.get("width", 0)
                height = photo.get("height", 0)

                # Get photographer info
                user = photo.get("user", {})
                photographer = user.get("name", "Unknown")
                photographer_url = user.get("links", {}).get("html", "")

                image_metadata = {
                    "id": image_id,
                    "filename": f"{photo['id']}.jpg",
                    "path": regular_url,
                    "raw_url": raw_url,
                    "width": width,
                    "height": height,
                    "size": 0,  # Size not available from API
                    "format": "jpg",
                    "source": self.plugin_id,
                    "title": photo.get("description")
                    or photo.get("alt_description")
                    or f"Photo by {photographer}",
                    "photographer": photographer,
                    "photographer_url": photographer_url,
                    "unsplash_id": photo["id"],
                    "created_at": photo.get("created_at"),
                }
                images.append(image_metadata)

            self._images = images
            self._last_scan = datetime.now()
            return images

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                print(
                    "Error: Unsplash API requires authentication. Please provide an API key in plugin settings."  # noqa: E501
                )
            elif e.response.status_code == 403:
                print("Error: Unsplash API access forbidden. Check your API key.")
            else:
                print(f"HTTP error fetching photos from Unsplash: {e.response.status_code} - {e}")
            # Return cached images if available
            return self._images.copy()
        except httpx.HTTPError as e:
            print(f"Error fetching photos from Unsplash: {e}")
            # Return cached images if available
            return self._images.copy()
        except Exception as e:
            print(f"Unexpected error in Unsplash plugin: {e}")
            import traceback

            traceback.print_exc()
            return self._images.copy()

    async def validate_config(self, config: dict[str, Any]) -> bool:
        """
        Validate plugin configuration.

        Args:
            config: Configuration dictionary

        Returns:
            True if configuration is valid
        """
        # API key is optional, but if provided should be a string
        if "api_key" in config:
            api_key = extract_config_value(config, "api_key", default="", converter=to_str)
            if api_key and not isinstance(api_key, str):
                return False

        # Category should be one of the valid options
        if "category" in config:
            category = extract_config_value(config, "category", default="popular", converter=to_str)
            valid_categories = ["popular", "latest", "oldest"]
            if category not in valid_categories:
                return False

        # Count should be a positive integer between 1 and 100
        if "count" in config:
            count = extract_config_value(config, "count", default=30, converter=to_int)
            if count < 1 or count > 100:  # Unsplash API limit
                return False
            # Also validate in configure method, but here we just check range

        return True

    async def configure(self, config: dict[str, Any]) -> None:
        """
        Configure the plugin with settings.

        Args:
            config: Configuration dictionary
        """
        await super().configure(config)

        if "api_key" in config:
            api_key = extract_config_value(config, "api_key", default="", converter=to_str)
            # Convert empty string or whitespace-only to None
            self.api_key = api_key.strip() if api_key and api_key.strip() else None

        if "category" in config:
            self.category = extract_config_value(config, "category", default="popular", converter=to_str)

        if "count" in config:
            count = extract_config_value(config, "count", default=30, converter=to_int)
            self.count = min(count, 100)  # Cap at 100 (Unsplash API limit)

        # Reset scan cache when config changes
        self._last_scan = None


# Register this plugin with pluggy
@hookimpl
def register_plugin_types() -> list[dict[str, Any]]:
    """Register UnsplashImagePlugin type."""
    return [UnsplashImagePlugin.get_plugin_metadata()]


@hookimpl
def create_plugin_instance(
    plugin_id: str,
    type_id: str,
    name: str,
    config: dict[str, Any],
) -> UnsplashImagePlugin | None:
    """Create an UnsplashImagePlugin instance."""
    if type_id != "unsplash":
        return None

    enabled = config.get("enabled", False)  # Default to disabled

    # Extract config values using utility functions
    api_key = extract_config_value(config, "api_key", default="", converter=to_str)
    api_key = api_key if api_key else None

    category = extract_config_value(config, "category", default="popular", converter=to_str)
    count = extract_config_value(config, "count", default=30, converter=to_int)

    return UnsplashImagePlugin(
        plugin_id=plugin_id,
        name=name,
        api_key=api_key,
        category=category,
        count=count,
        enabled=enabled,
    )


@hookimpl
async def handle_plugin_config_update(
    type_id: str,
    config: dict[str, Any],
    enabled: bool | None,
    db_type: Any,
    session: Any,
) -> dict[str, Any] | None:
    """Handle Unsplash plugin configuration update and instance management."""
    if type_id != "unsplash":
        return None

    def normalize_config(c: dict[str, Any]) -> dict[str, Any]:
        """Normalize config values."""
        api_key = extract_config_value(c, "api_key", default="", converter=to_str)
        return {
            "api_key": api_key if api_key else None,
            "category": extract_config_value(c, "category", default="popular", converter=to_str),
            "count": extract_config_value(c, "count", default=30, converter=to_int),
        }

    manager_config = InstanceManagerConfig(
        type_id="unsplash",
        single_instance=True,
        instance_id="unsplash-instance",
        normalize_config=normalize_config,
        default_instance_name="Unsplash",
    )

    return await handle_plugin_config_update_generic(
        type_id, config, enabled, db_type, session, manager_config
    )




