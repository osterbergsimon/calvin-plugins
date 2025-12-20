"""Test plugin for plugin installation testing."""

from typing import Any

from app.plugins.base import PluginType
from app.plugins.hooks import hookimpl
from app.plugins.protocols import ServicePlugin


class TestServicePlugin(ServicePlugin):
    """Test service plugin for installation testing."""

    @classmethod
    def get_plugin_metadata(cls) -> dict[str, Any]:
        """Get plugin metadata for registration."""
        return {
            "type_id": "test_plugin",
            "plugin_type": PluginType.SERVICE,
            "name": "Test Plugin",
            "description": "A basic test plugin for plugin installation testing",
            "version": "1.0.0",
            "common_config_schema": {
                "message": {
                    "type": "string",
                    "description": "Test message to display",
                    "default": "Hello from test plugin!",
                    "ui": {
                        "component": "input",
                        "placeholder": "Enter a message",
                        "validation": {
                            "required": False,
                        },
                    },
                },
            },
            "display_schema": {
                "type": "api",
                "api_endpoint": None,
                "method": None,
                "data_schema": None,
                "render_template": "iframe",
            },
            "plugin_class": cls,
        }

    def __init__(
        self, plugin_id: str, name: str, message: str = "Hello from test plugin!", enabled: bool = True
    ):
        """
        Initialize test service plugin.

        Args:
            plugin_id: Unique identifier for the plugin
            name: Human-readable name
            message: Test message to display
            enabled: Whether the plugin is enabled
        """
        super().__init__(plugin_id, name, enabled)
        self.message = message

    async def initialize(self) -> None:
        """Initialize the plugin."""
        pass

    async def cleanup(self) -> None:
        """Cleanup plugin resources."""
        pass

    async def get_content(self) -> dict[str, Any]:
        """
        Get service content for display.

        Returns:
            Dictionary with content information
        """
        return {
            "type": "iframe",
            "url": "about:blank",
            "config": {
                "message": self.message,
            },
        }

    async def validate_config(self, config: dict[str, Any]) -> bool:
        """
        Validate plugin configuration.

        Args:
            config: Configuration dictionary

        Returns:
            True if configuration is valid
        """
        # Accept any configuration for testing purposes
        return True


# Register this plugin with pluggy
@hookimpl
def register_plugin_types() -> list[dict[str, Any]]:
    """Register TestServicePlugin type."""
    return [TestServicePlugin.get_plugin_metadata()]


@hookimpl
def create_plugin_instance(
    plugin_id: str,
    type_id: str,
    name: str,
    config: dict[str, Any],
) -> TestServicePlugin | None:
    """Create a TestServicePlugin instance."""
    if type_id != "test_plugin":
        return None

    enabled = config.get("enabled", False)  # Default to disabled
    message = config.get("message", "Hello from test plugin!")

    # Handle schema objects
    if isinstance(message, dict):
        message = message.get("value") or message.get("default") or "Hello from test plugin!"
    message = str(message) if message else "Hello from test plugin!"

    return TestServicePlugin(
        plugin_id=plugin_id,
        name=name,
        message=message,
        enabled=enabled,
    )

