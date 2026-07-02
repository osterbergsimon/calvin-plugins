"""Test plugin with a web-component frontend for plugin installation testing.

The smallest legal web-component plugin under the Calvin plugin contract 1.0
(the tier-2 escape hatch): the class declares `display_schema.kind:
"web-component"`, and `frontend/dist.js` ships a hand-written custom element
the host serves at /api/plugins/test_plugin_frontend/static/dist.js. The host
mounts the element and assigns `fetch()`'s payload to its `data` property.
"""

from typing import Any

from app.plugins.definitions import PluginMetadata
from app.plugins.protocols import ServicePlugin


class TestFrontendServicePlugin(ServicePlugin):
    """Test service plugin with frontend assets for installation testing."""

    metadata = PluginMetadata(
        type_id="test_plugin_frontend",
        name="Test Plugin with Frontend",
        description="A test plugin with frontend components for testing frontend installation",
        supports_multiple_instances=False,
        default_instance_name="Test Plugin with Frontend",
        instance_config_schema={
            "message": {
                "type": "string",
                "description": "Test message to display",
                "default": "test plugin frontend OK",
                "ui": {
                    "component": "input",
                    "placeholder": "Enter a message",
                },
            },
        },
        display_schema={
            "kind": "web-component",
            "element": "calvin-test-frontend",
            "module": "dist.js",
        },
    )

    async def fetch(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Return the payload the host assigns to the custom element's `data`."""
        return {
            "message": self.config.get("message") or "test plugin frontend OK",
            "plugin_id": self.plugin_id,
        }
