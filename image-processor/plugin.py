"""Image Processor backend plugin - processes images when uploaded via events."""

import asyncio
import hashlib
from pathlib import Path
from typing import Any

from loguru import logger

from app.plugins.base import PluginType
from app.plugins.hooks import hookimpl
from app.plugins.protocols import BackendPlugin
from app.plugins.utils.config import extract_config_value, to_bool, to_int
from app.plugins.utils.instance_manager import (
    InstanceManagerConfig,
    handle_plugin_config_update_generic,
)

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
            "supports_multiple_instances": True,  # Multi-instance plugin
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
        max_width = extract_config_value(config, "max_width", default=1920, converter=to_int)
        max_height = extract_config_value(config, "max_height", default=1080, converter=to_int)
        if max_width <= 0 or max_height <= 0:
            return False

        # Check thumbnail size if enabled
        generate_thumbnails = extract_config_value(config, "generate_thumbnails", default=True, converter=to_bool)
        if generate_thumbnails:
            thumbnail_size = extract_config_value(config, "thumbnail_size", default=300, converter=to_int)
            if thumbnail_size <= 0:
                return False

        return True

    async def configure(self, config: dict[str, Any]) -> None:
        """
        Configure the plugin with settings.

        Args:
            config: Configuration dictionary
        """
        await super().configure(config)
        # Configuration is stored via get_config() from the base class
        # Individual values are extracted when needed in _handle_image_uploaded

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

    enabled = extract_config_value(config, "enabled", default=True, converter=to_bool)
    plugin = ImageProcessorPlugin(plugin_id, name, enabled)
    return plugin


@hookimpl
async def handle_plugin_config_update(
    type_id: str,
    config: dict[str, Any],
    enabled: bool | None,
    db_type: Any,
    session: Any,
) -> dict[str, Any] | None:
    """Handle Image Processor plugin configuration update and instance management."""
    if type_id != "image-processor":
        return None

    def normalize_config(c: dict[str, Any]) -> dict[str, Any]:
        """Normalize config values."""
        return {
            "enabled": extract_config_value(c, "enabled", default=True, converter=to_bool),
            "resize_enabled": extract_config_value(c, "resize_enabled", default=True, converter=to_bool),
            "max_width": extract_config_value(c, "max_width", default=1920, converter=to_int),
            "max_height": extract_config_value(c, "max_height", default=1080, converter=to_int),
            "generate_thumbnails": extract_config_value(c, "generate_thumbnails", default=True, converter=to_bool),
            "thumbnail_size": extract_config_value(c, "thumbnail_size", default=300, converter=to_int),
        }

    def generate_instance_id(c: dict[str, Any], t_id: str) -> str:
        """Generate instance ID from config values."""
        # Create a hash from config to generate unique ID
        # For image-processor, we could use a combination of settings
        config_str = f"{c.get('max_width', 1920)}_{c.get('max_height', 1080)}_{c.get('thumbnail_size', 300)}"
        config_hash = hashlib.md5(config_str.encode()).hexdigest()[:8]
        return f"{t_id}-{config_hash}"

    manager_config = InstanceManagerConfig(
        type_id="image-processor",
        single_instance=False,  # Multi-instance plugin
        generate_instance_id=generate_instance_id,
        normalize_config=normalize_config,
        default_instance_name="Image Processor",
    )

    return await handle_plugin_config_update_generic(
        type_id, config, enabled, db_type, session, manager_config
    )
