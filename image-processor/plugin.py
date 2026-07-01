"""Image Processor backend plugin - processes images when uploaded via events.

Plugin contract 1.0: one declarative class with `metadata = PluginMetadata(...)`,
config declared once in `metadata.instance_config_schema` and read from
`self.config`. The event-driven surface (`get_subscribed_events` /
`handle_event`) and the service-provider surface (`provide_service` /
`get_provided_services`) are unchanged.
"""

import asyncio
from pathlib import Path
from typing import Any

from loguru import logger

from app.plugins.definitions import PluginMetadata
from app.plugins.protocols import BackendPlugin


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

    metadata = PluginMetadata(
        type_id="image-processor",
        name="Image Processor",
        description=(
            "Automatically processes images when uploaded (resize, optimize, "
            "generate thumbnails). Demonstrates event system usage."
        ),
        default_instance_name="Image Processor",
        instance_label="Processor",
        # Same processing settings -> same instance
        instance_identity=["max_width", "max_height", "thumbnail_size"],
        instance_config_schema={
            "processing_enabled": {
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
        ui_actions=[
            {
                "id": "save",
                "type": "save",
                "label": "Save Settings",
                "style": "primary",
                "scope": "instance",
            },
        ],
    )

    def __init__(self, plugin_id: str, name: str, enabled: bool = True):
        """Initialize image processor plugin."""
        super().__init__(plugin_id, name, enabled)
        self._processed_count = 0
        self._error_count = 0

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

    @classmethod
    async def validate_config(cls, config: dict[str, Any]) -> bool:
        """Require positive dimensions; positive thumbnail size when enabled."""
        normalized = cls.normalize_config(config)
        if int(normalized.get("max_width") or 0) <= 0:
            return False
        if int(normalized.get("max_height") or 0) <= 0:
            return False
        if normalized.get("generate_thumbnails") and int(normalized.get("thumbnail_size") or 0) <= 0:
            return False
        return True

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    async def get_subscribed_events(self) -> list[str]:
        """Return list of event types this plugin subscribes to."""
        if not self.enabled:
            return []

        config = self.get_config()
        if not config.get("processing_enabled", True):
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

        try:
            config = self.get_config()
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
                logger.debug(
                    f"Image Processor: Would generate thumbnail for {filename} "
                    f"({thumbnail_size}x{thumbnail_size})"
                )
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

    # ------------------------------------------------------------------
    # Service provider
    # ------------------------------------------------------------------

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
