"""Tests for the Test Plugin with Frontend fixture (plugin contract 1.0).

This is the web-component (tier-2 escape hatch) fixture: the display schema is
`kind: "web-component"` and the plugin ships a hand-written custom element in
frontend/dist.js.

Run from the calvin backend directory so `app.*` imports resolve:
    cd calvin/backend
    uv run pytest ../../calvin-plugins/test-plugin-frontend/test_test_plugin_frontend.py
"""

import importlib.util
import json
import types
from pathlib import Path

import pytest

try:
    from app.plugins.definitions import PluginMetadata
    from app.plugins.loader import PluginLoader
    from app.plugins.protocols import ServicePlugin
except ImportError as e:  # pragma: no cover
    pytest.skip(f"Backend dependencies not available: {e}", allow_module_level=True)

PLUGIN_DIR = Path(__file__).parent


def _load_plugin_module():
    spec = importlib.util.spec_from_file_location(
        "test_plugin_frontend_under_test", PLUGIN_DIR / "plugin.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


plugin_module = _load_plugin_module()
# Aliased so pytest doesn't collect the plugin class as a test class.
_PluginClass = plugin_module.TestFrontendServicePlugin


@pytest.fixture
async def plugin():
    instance = _PluginClass(
        plugin_id="test-plugin-frontend-instance",
        name="Test Plugin with Frontend",
        enabled=True,
    )
    await instance.configure({})
    return instance


class TestContractShape:
    """The plugin conforms to contract 1.0: one class, declarative metadata."""

    def test_discoverable_by_loader(self):
        loader = PluginLoader()
        module = types.ModuleType("installed_plugin_test_plugin_frontend")
        module.plugin_class = _PluginClass
        assert loader.register_module(module) == ["test_plugin_frontend"]

    def test_no_module_level_hooks(self):
        for hook in (
            "register_plugin_types",
            "create_plugin_instance",
            "handle_plugin_config_update",
        ):
            assert not hasattr(plugin_module, hook), hook

    def test_metadata(self):
        md = _PluginClass.metadata
        assert isinstance(md, PluginMetadata)
        assert md.type_id == "test_plugin_frontend"
        assert md.supports_multiple_instances is False
        assert "message" in md.instance_config_schema

    def test_display_schema_is_web_component(self):
        md = _PluginClass.metadata
        assert md.display_schema["kind"] == "web-component"
        assert md.display_schema["element"] == "calvin-test-frontend"
        assert md.display_schema["module"] == "dist.js"

    def test_is_service_plugin(self):
        assert issubclass(_PluginClass, ServicePlugin)


class TestFrontendAssets:
    """The web-component asset ships with the plugin and matches the schema."""

    def test_dist_js_exists_and_defines_declared_element(self):
        dist = PLUGIN_DIR / "frontend" / "dist.js"
        assert dist.is_file()
        source = dist.read_text()
        element = _PluginClass.metadata.display_schema["element"]
        assert f'customElements.define("{element}"' in source

    def test_manifest_ships_dist_js(self):
        manifest = json.loads((PLUGIN_DIR / "plugin.json").read_text())
        assert "frontend/dist.js" in manifest["files"]["include"]
        assert manifest["api_version"] == 1


class TestFetch:
    async def test_fetch_returns_default_message(self, plugin):
        payload = await plugin.fetch()
        assert payload["message"] == "test plugin frontend OK"
        assert payload["plugin_id"] == "test-plugin-frontend-instance"

    async def test_fetch_returns_configured_message(self, plugin):
        await plugin.configure({"message": "hello frontend"})
        payload = await plugin.fetch()
        assert payload["message"] == "hello frontend"
