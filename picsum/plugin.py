"""Picsum Photos image plugin (no API key required)."""

from datetime import datetime
from typing import Any

import httpx

from app.plugins.base import PluginType
from app.plugins.hooks import hookimpl
from app.plugins.protocols import ImagePlugin


class PicsumImagePlugin(ImagePlugin):
    """Picsum Photos image plugin for fetching random images without API key."""

    @classmethod
    def get_plugin_metadata(cls) -> dict[str, Any]:
        """Get plugin metadata for registration."""
        return {
            "type_id": "picsum",
            "plugin_type": PluginType.IMAGE,
            "name": "Picsum Photos",
            "description": "Random high-quality images from Picsum Photos (no API key required)",
            "version": "1.0.0",
            "common_config_schema": {
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
            "plugin_class": cls,
        }

    def __init__(
        self,
        plugin_id: str,
        name: str,
        count: int = 30,
        enabled: bool = True,
    ):
        """
        Initialize Picsum Photos image plugin.

        Args:
            plugin_id: Unique identifier for the plugin
            name: Human-readable name
            count: Number of photos to fetch (default: 30)
            enabled: Whether the plugin is enabled
        """
        super().__init__(plugin_id, name, enabled)
        self.count = count
        self.base_url = "https://picsum.photos"
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
            image_id: Image identifier (Picsum photo ID)

        Returns:
            Image metadata dictionary or None if not found
        """
        await self.scan_images()
        return next((img for img in self._images if img["id"] == image_id), None)

    async def get_image_data(self, image_id: str) -> bytes | None:
        """
        Get image file data by ID.

        Args:
            image_id: Image identifier (Picsum photo ID)

        Returns:
            Image file data as bytes or None if not found
        """
        # Find the image to get its URL
        image = await self.get_image(image_id)
        if not image:
            return None

        # Get the image URL
        image_url = image.get("url") or image.get("raw_url")
        if not image_url:
            return None

        # Fetch the image
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(image_url)
                response.raise_for_status()
                return response.content
            except httpx.HTTPError as e:
                print(f"Error fetching image from Picsum: {e}")
                return None

    async def scan_images(self) -> list[dict[str, Any]]:
        """
        Scan for new/updated images from Picsum Photos.

        Returns:
            List of image metadata dictionaries
        """
        # Check if we need to rescan (avoid too frequent API calls)
        if self._last_scan:
            time_since_scan = (datetime.now() - self._last_scan).total_seconds()
            if time_since_scan < self._scan_interval:
                return self._images.copy()

        try:
            # Use Picsum Photos API to get list of images
            # The /v2/list endpoint returns a list of available images
            url = f"{self.base_url}/v2/list"
            params = {
                "page": 1,
                "limit": min(self.count, 100),  # Picsum API limit is 100 per page
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                photos = response.json()

            # Convert Picsum photos to our image format
            images = []
            for photo in photos:
                # Generate a unique ID from the photo ID
                image_id = f"picsum-{photo['id']}"

                # Get image URLs
                # Picsum provides images at different sizes
                # We'll use the regular size (800x600) for display
                regular_url = f"{self.base_url}/id/{photo['id']}/800/600"
                raw_url = f"{self.base_url}/id/{photo['id']}/1920/1080"  # Full HD for download

                # Get dimensions from photo data
                width = photo.get("width", 1920)
                height = photo.get("height", 1080)

                # Get author info
                author = photo.get("author", "Unknown")
                author_url = photo.get("author_url", "")

                image_metadata = {
                    "id": image_id,
                    "filename": f"{photo['id']}.jpg",
                    "path": regular_url,
                    "url": regular_url,
                    "raw_url": raw_url,
                    "width": width,
                    "height": height,
                    "size": 0,  # Size not available from API
                    "format": "jpg",
                    "source": self.plugin_id,
                    "title": f"Photo by {author}",
                    "photographer": author,
                    "photographer_url": author_url,
                    "picsum_id": photo["id"],
                    "created_at": photo.get(
                        "download_url", ""
                    ),  # Picsum doesn't provide created_at
                }
                images.append(image_metadata)

            self._images = images
            self._last_scan = datetime.now()
            return images

        except httpx.HTTPStatusError as e:
            print(f"HTTP error fetching photos from Picsum: {e.response.status_code} - {e}")
            # Return cached images if available
            return self._images.copy()
        except httpx.HTTPError as e:
            print(f"Error fetching photos from Picsum: {e}")
            # Return cached images if available
            return self._images.copy()
        except Exception as e:
            print(f"Unexpected error in Picsum plugin: {e}")
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
        # Count should be a positive integer
        if "count" in config:
            try:
                count = int(config["count"])
                if count < 1 or count > 100:  # Picsum API limit
                    return False
            except (ValueError, TypeError):
                return False

        return True

    async def configure(self, config: dict[str, Any]) -> None:
        """
        Configure the plugin with settings.

        Args:
            config: Configuration dictionary
        """
        await super().configure(config)

        if "count" in config:
            self.count = min(int(config["count"]), 100)  # Cap at 100

        # Reset scan cache when config changes
        self._last_scan = None


# Register this plugin with pluggy
@hookimpl
def register_plugin_types() -> list[dict[str, Any]]:
    """Register PicsumImagePlugin type."""
    return [PicsumImagePlugin.get_plugin_metadata()]


@hookimpl
def create_plugin_instance(
    plugin_id: str,
    type_id: str,
    name: str,
    config: dict[str, Any],
) -> PicsumImagePlugin | None:
    """Create a PicsumImagePlugin instance."""
    if type_id != "picsum":
        return None

    enabled = config.get("enabled", False)  # Default to disabled

    # Extract config values
    count = config.get("count", 30)

    # Handle schema objects
    if isinstance(count, dict):
        count = count.get("value") or count.get("default") or 30
    try:
        count = int(count) if count else 30
    except (ValueError, TypeError):
        count = 30

    return PicsumImagePlugin(
        plugin_id=plugin_id,
        name=name,
        count=count,
        enabled=enabled,
    )

