"""Tests for the Test Plugin fixture (plugin contract 1.0).

Run from the calvin backend directory so `app.*` imports resolve:
    cd calvin/backend
    uv run pytest ../../calvin-plugins/test-plugin/test_test_plugin.py
"""

import importlib.util
import types
from pathlib import Path

import pytest

try:
    from app.plugins.definitions import PluginMetadata
    from app.plugins.loader import PluginLoader
    from app.plugins.protocols import ServicePlugin
except ImportError as e:  # pragma: no cover
    pytest.skip(f"Backend dependencies not available: {e}", allow_module_level=True)


def _load_plugin_module():
    plugin_path = Path(__file__).parent / "plugin.py"
    spec = importlib.util.spec_from_file_location("test_plugin_under_test", plugin_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


plugin_module = _load_plugin_module()
# Aliased so pytest doesn't collect the plugin class as a test class.
_PluginClass = plugin_module.TestServicePlugin


@pytest.fixture
async def plugin():
    instance = _PluginClass(plugin_id="test-plugin-instance", name="Test Plugin", enabled=True)
    await instance.configure({})
    return instance


class TestContractShape:
    """The plugin conforms to contract 1.0: one class, declarative metadata."""

    def test_discoverable_by_loader(self):
        loader = PluginLoader()
        module = types.ModuleType("installed_plugin_test_plugin")
        module.plugin_class = _PluginClass
        assert loader.register_module(module) == ["test_plugin"]

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
        assert md.type_id == "test_plugin"
        assert md.supports_multiple_instances is False
        assert md.fixed_instance_id == "test-plugin-instance"
        assert "message" in md.instance_config_schema

    def test_display_schema_is_status(self):
        md = _PluginClass.metadata
        assert md.display_schema["kind"] == "status"
        assert md.display_schema["item"]["value_path"] == "$.message"

    def test_statusbar_schema_is_status(self):
        # The fixture also exercises the statusbar kind namespace.
        md = _PluginClass.metadata
        assert md.statusbar_schema["kind"] == "status"
        assert md.statusbar_schema["item"]["value_path"] == "$.message"

    def test_is_service_plugin(self):
        assert issubclass(_PluginClass, ServicePlugin)


class TestFetch:
    async def test_fetch_returns_default_message(self, plugin):
        payload = await plugin.fetch()
        assert payload["message"] == "test plugin OK"
        assert payload["plugin_id"] == "test-plugin-instance"

    async def test_fetch_returns_configured_message(self, plugin):
        await plugin.configure({"message": "custom message"})
        payload = await plugin.fetch()
        assert payload["message"] == "custom message"

    async def test_validate_config_accepts_anything(self):
        # No required fields — the schema-driven default validation passes.
        assert await _PluginClass.validate_config({}) is True
        assert await _PluginClass.validate_config({"message": "hello"}) is True
