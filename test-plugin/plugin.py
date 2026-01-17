"""Test plugin for plugin installation testing."""

from typing import Any

from app.plugins.base import PluginType
from app.plugins.hooks import hookimpl
from app.plugins.protocols import ServicePlugin
from app.plugins.utils.config import extract_config_value, to_str
from app.plugins.utils.instance_manager import (
    InstanceManagerConfig,
    handle_plugin_config_update_generic,
)


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
            "supports_multiple_instances": False,  # Single-instance plugin
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
            "instance_config_schema": {},  # No instance-specific settings (single-instance)
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
        # Message is optional and can be any string
        if "message" in config:
            message = extract_config_value(config, "message", default="Hello from test plugin!", converter=to_str)
            if message and not isinstance(message, str):
                return False
        return True

    async def configure(self, config: dict[str, Any]) -> None:
        """
        Configure the plugin with settings.

        Args:
            config: Configuration dictionary
        """
        await super().configure(config)

        if "message" in config:
            self.message = extract_config_value(config, "message", default="Hello from test plugin!", converter=to_str)


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

    # Extract config values using utility functions
    message = extract_config_value(config, "message", default="Hello from test plugin!", converter=to_str)

    return TestServicePlugin(
        plugin_id=plugin_id,
        name=name,
        message=message,
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
    """Handle Test Plugin configuration update and instance management."""
    if type_id != "test_plugin":
        return None

    def normalize_config(c: dict[str, Any]) -> dict[str, Any]:
        """Normalize config values."""
        return {
            "message": extract_config_value(c, "message", default="Hello from test plugin!", converter=to_str),
        }

    manager_config = InstanceManagerConfig(
        type_id="test_plugin",
        single_instance=True,
        instance_id="test-plugin-instance",
        normalize_config=normalize_config,
        default_instance_name="Test Plugin",
    )

    return await handle_plugin_config_update_generic(
        type_id, config, enabled, db_type, session, manager_config
    )

