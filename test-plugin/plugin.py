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
        name="Test plugin",
        description="For plugin developers: checks that installing works.",
        icon="mdi:flask-outline",
        supports_multiple_instances=False,
        fixed_instance_id="test-plugin-instance",
        default_instance_name="Test plugin",
        instance_config_schema={
            "message": {
                "type": "string",
                "label": "Message",
                "description": "Text the test shows.",
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
