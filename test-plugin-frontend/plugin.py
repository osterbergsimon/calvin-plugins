"""Test plugin with frontend components for plugin installation testing."""

from typing import Any

from app.plugins.hooks import hookimpl
from app.plugins.protocols import ServicePlugin
from app.plugins.sdk.service import (
    ServiceConfigField,
    build_service_plugin_metadata,
    create_service_plugin_instance,
)


SERVICE_FIELDS = (
    ServiceConfigField(
        "message",
        default="Hello from test plugin with frontend!",
        converter=str,
        transform=lambda value: str(value) if value else "Hello from test plugin with frontend!",
    ),
)


class TestFrontendServicePlugin(ServicePlugin):
    """Test service plugin with frontend components for installation testing."""

    @classmethod
    def get_plugin_metadata(cls) -> dict[str, Any]:
        """Get plugin metadata for registration."""
        return build_service_plugin_metadata(
            type_id="test_plugin_frontend",
            name="Test Plugin with Frontend",
            description="A test plugin with frontend components for testing frontend installation",
            plugin_class=cls,
            supports_multiple_instances=False,
            common_config_schema={
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
            display_schema={
                "type": "api",
                "api_endpoint": None,
                "method": None,
                "data_schema": None,
                "render_template": "iframe",
            },
        )

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
    return create_service_plugin_instance(
        TestFrontendServicePlugin,
        expected_type_id="test_plugin_frontend",
        plugin_id=plugin_id,
        type_id=type_id,
        name=name,
        config=config,
        fields=SERVICE_FIELDS,
    )
