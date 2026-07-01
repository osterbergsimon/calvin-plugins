"""Test plugin for plugin installation testing.

The smallest legal service plugin under the Calvin plugin contract 1.0: one
declarative class, one config field, a `status` display schema, a `status`
statusbar schema (so it also exercises the statusbar namespace), and `fetch()`
as the single data verb. Used by the host's install/contract tests.
"""

from typing import Any

from app.plugins.definitions import PluginMetadata
from app.plugins.protocols import ServicePlugin


class TestServicePlugin(ServicePlugin):
    """Test service plugin for installation testing."""

    metadata = PluginMetadata(
        type_id="test_plugin",
        name="Test Plugin",
        description="A basic test plugin for plugin installation testing",
        supports_multiple_instances=False,
        fixed_instance_id="test-plugin-instance",
        default_instance_name="Test Plugin",
        instance_config_schema={
            "message": {
                "type": "string",
                "description": "Test message to display",
                "default": "test plugin OK",
                "ui": {
                    "component": "input",
                    "placeholder": "Enter a message",
                },
            },
        },
        display_schema={
            "kind": "status",
            "item": {"label": "Test", "value_path": "$.message"},
        },
        statusbar_schema={
            "kind": "status",
            "item": {"label": "Test", "value_path": "$.message"},
        },
    )

    async def fetch(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Return the payload the status schemas bind to."""
        return {
            "message": self.config.get("message") or "test plugin OK",
            "plugin_id": self.plugin_id,
        }
