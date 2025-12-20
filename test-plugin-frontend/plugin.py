"""Test plugin with frontend components for plugin installation testing."""

from typing import Any

from app.plugins.base import PluginType
from app.plugins.hooks import hookimpl
from app.plugins.protocols import ServicePlugin


class TestFrontendServicePlugin(ServicePlugin):
    """Test service plugin with frontend components for installation testing."""

    @classmethod
    def get_plugin_metadata(cls) -> dict[str, Any]:
        """Get plugin metadata for registration."""
        return {
            "type_id": "test_plugin_frontend",
            "plugin_type": PluginType.SERVICE,
            "name": "Test Plugin with Frontend",
            "description": "A test plugin with frontend components for testing frontend installation",
            "version": "1.0.0",
            "common_config_schema": {
                "message": {
                    "type": "string",
                    "description": "Test message to display",
                    "default": "Hello from test plugin with frontend!",
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
        self,
        plugin_id: str,
        name: str,
        message: str = "Hello from test plugin with frontend!",
        enabled: bool = True,
    ):
        super().__init__(plugin_id, name, enabled)
        self.message = message

    async def initialize(self) -> None:
        """Initialize the plugin."""
        pass

    async def cleanup(self) -> None:
        """Cleanup plugin resources."""
        pass

    async def get_content(self) -> dict[str, Any]:
        """Get service content for display."""
        return {
            "type": "iframe",
            "url": "about:blank",
            "config": {
                "message": self.message,
            },
        }

    async def validate_config(self, config: dict[str, Any]) -> bool:
        """Validate plugin configuration."""
        return True


@hookimpl
def register_plugin_types() -> list[dict[str, Any]]:
    """Register TestFrontendServicePlugin type."""
    return [TestFrontendServicePlugin.get_plugin_metadata()]


@hookimpl
def create_plugin_instance(
    plugin_id: str,
    type_id: str,
    name: str,
    config: dict[str, Any],
) -> TestFrontendServicePlugin | None:
    """Create a TestFrontendServicePlugin instance."""
    if type_id != "test_plugin_frontend":
        return None

    enabled = config.get("enabled", False)
    message = config.get("message", "Hello from test plugin with frontend!")

    if isinstance(message, dict):
        message = (
            message.get("value")
            or message.get("default")
            or "Hello from test plugin with frontend!"
        )
    message = str(message) if message else "Hello from test plugin with frontend!"

    return TestFrontendServicePlugin(
        plugin_id=plugin_id,
        name=name,
        message=message,
        enabled=enabled,
    )

