"""Image Processor backend plugin - processes images when uploaded via events."""

import asyncio
from pathlib import Path
from typing import Any

from loguru import logger

from app.plugins.base import PluginType
from app.plugins.hooks import hookimpl
from app.plugins.protocols import BackendPlugin

# Loguru automatically includes module/function info in logs


class ImageProcessorPlugin(BackendPlugin):
    """Image Processor backend plugin that processes images when they're uploaded.

    This plugin demonstrates the event system by:
    - Subscribing to 'image_uploaded' events
    - Processing images (resize, optimize, generate thumbnails)
    - Emitting 'image_processed' events when done

    This is an example plugin showing how plugins can:
    1. Subscribe to system events
    2. Process data asynchronously
    3. Emit custom events for other plugins
    """

    @classmethod
    def get_plugin_metadata(cls) -> dict[str, Any]:
        """Get plugin metadata for registration."""
        return {
            "type_id": "image-processor",
            "plugin_type": PluginType.BACKEND,
            "name": "Image Processor",
            "description": "Automatically processes images when uploaded (resize, optimize, generate thumbnails). Demonstrates event system usage.",
            "version": "1.0.0",
            "common_config_schema": {},
            "instance_config_schema": {
                "enabled": {
                    "type": "boolean",
                    "description": "Enable image processing",
                    "default": True,
                },
                "resize_enabled": {
                    "type": "boolean",
                    "description": "Resize large images",
                    "default": True,
                },
                "max_width": {
                    "type": "integer",
                    "description": "Maximum image width in pixels",
                    "default": 1920,
                    "ui": {
                        "component": "input",
                        "type": "number",
                        "min": 100,
                        "max": 10000,
                    },
                },
                "max_height": {
                    "type": "integer",
                    "description": "Maximum image height in pixels",
                    "default": 1080,
                    "ui": {
                        "component": "input",
                        "type": "number",
                        "min": 100,
                        "max": 10000,
                    },
                },
                "generate_thumbnails": {
                    "type": "boolean",
                    "description": "Generate thumbnail versions",
                    "default": True,
                },
                "thumbnail_size": {
                    "type": "integer",
                    "description": "Thumbnail size in pixels",
                    "default": 300,
                    "ui": {
                        "component": "input",
                        "type": "number",
                        "min": 50,
                        "max": 1000,
                    },
                },
            },
        }

    def __init__(self, plugin_id: str, name: str, enabled: bool = True):
        """Initialize image processor plugin."""
        super().__init__(plugin_id, name, enabled)
        self._processed_count = 0
        self._error_count = 0

    @property
    def plugin_type(self) -> PluginType:
        """Return backend plugin type."""
        return PluginType.BACKEND

    async def initialize(self) -> None:
        """Initialize the plugin."""
        logger.info(f"Image Processor plugin {self.plugin_id} initialized")
        self._processed_count = 0
        self._error_count = 0

    async def cleanup(self) -> None:
        """Cleanup plugin resources."""
        logger.info(
            f"Image Processor plugin {self.plugin_id} cleaned up. "
            f"Processed {self._processed_count} images, {self._error_count} errors"
        )

    async def validate_config(self, config: dict[str, Any]) -> bool:
        """Validate plugin configuration."""
        # Check that max dimensions are positive
        max_width = config.get("max_width", 1920)
        max_height = config.get("max_height", 1080)
        if max_width <= 0 or max_height <= 0:
            return False

        # Check thumbnail size if enabled
        if config.get("generate_thumbnails", True):
            thumbnail_size = config.get("thumbnail_size", 300)
            if thumbnail_size <= 0:
                return False

        return True

    async def get_subscribed_events(self) -> list[str]:
        """Return list of event types this plugin subscribes to."""
        if not self.enabled:
            return []

        config = self.get_config()
        if not config.get("enabled", True):
            return []

        # Subscribe to image_uploaded events
        return ["image_uploaded"]

    async def handle_event(
        self, event_type: str, event_data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Handle system events."""
        if event_type == "image_uploaded":
            return await self._handle_image_uploaded(event_data)

        return None

    async def _handle_image_uploaded(self, event_data: dict[str, Any]) -> dict[str, Any]:
        """Handle image_uploaded event."""
        image_id = event_data.get("image_id")
        filename = event_data.get("filename")
        image_path = event_data.get("path")
        source_plugin_id = event_data.get("plugin_id")

        if not image_path or not Path(image_path).exists():
            logger.warning(
                f"Image Processor: Image path not found for {image_id}: {image_path}"
            )
            self._error_count += 1
            return {"success": False, "error": "Image path not found"}

        logger.info(
            f"Image Processor: Processing image {image_id} ({filename}) "
            f"from {source_plugin_id}"
        )

        config = self.get_config()

        try:
            # Process the image (simplified example - in real implementation,
            # you would use PIL/Pillow or similar to actually resize/optimize)
            processing_results = {
                "image_id": image_id,
                "filename": filename,
                "original_path": image_path,
            }

            # Simulate image processing
            if config.get("resize_enabled", True):
                max_width = config.get("max_width", 1920)
                max_height = config.get("max_height", 1080)
                logger.debug(
                    f"Image Processor: Would resize {filename} to max {max_width}x{max_height}"
                )
                processing_results["resized"] = True
                processing_results["max_dimensions"] = {"width": max_width, "height": max_height}

            if config.get("generate_thumbnails", True):
                thumbnail_size = config.get("thumbnail_size", 300)
                logger.debug(f"Image Processor: Would generate thumbnail for {filename} ({thumbnail_size}x{thumbnail_size})")
                processing_results["thumbnail_generated"] = True
                processing_results["thumbnail_size"] = thumbnail_size

            # Simulate processing delay
            await asyncio.sleep(0.1)

            self._processed_count += 1

            # Emit image_processed event (fire-and-forget)
            # Other plugins can subscribe to this event if needed
            await self.emit_event(
                "image_processed",
                {
                    "image_id": image_id,
                    "filename": filename,
                    "original_path": image_path,
                    "processor_id": self.plugin_id,
                    "processing_results": processing_results,
                },
                wait_for_handlers=False,  # Fire-and-forget
            )

            logger.info(f"Image Processor: Successfully processed {filename}")

            return {
                "success": True,
                "message": f"Processed {filename}",
                "processing_results": processing_results,
            }

        except Exception as e:
            logger.error(f"Image Processor: Error processing {filename}: {e}", exc_info=True)
            self._error_count += 1

            # Emit error event (fire-and-forget)
            await self.emit_event(
                "image_processing_failed",
                {
                    "image_id": image_id,
                    "filename": filename,
                    "error": str(e),
                    "processor_id": self.plugin_id,
                },
                wait_for_handlers=False,
            )

            return {"success": False, "error": str(e)}

    async def get_processing_stats(self) -> dict[str, Any]:
        """Get processing statistics (example of providing a service to other plugins)."""
        return {
            "processed_count": self._processed_count,
            "error_count": self._error_count,
            "total_processed": self._processed_count + self._error_count,
        }

    async def provide_service(self, service_name: str, **kwargs) -> Any:
        """Provide service to other plugins."""
        if service_name == "get_processing_stats":
            return await self.get_processing_stats()
        return None

    async def get_provided_services(self) -> list[str]:
        """Return list of services this plugin provides."""
        return ["get_processing_stats"]


# Pluggy hooks for plugin registration
@hookimpl
def register_plugin_types() -> list[dict[str, Any]]:
    """Register image processor plugin type."""
    return [ImageProcessorPlugin.get_plugin_metadata()]


@hookimpl
def create_plugin_instance(
    plugin_id: str,
    type_id: str,
    name: str,
    config: dict[str, Any],
) -> BackendPlugin | None:
    """Create an image processor plugin instance."""
    if type_id != "image-processor":
        return None

    plugin = ImageProcessorPlugin(plugin_id, name, config.get("enabled", True))
    return plugin
