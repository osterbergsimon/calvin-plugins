"""Tests for the SL Departures plugin (plugin contract 1.0).

Run from the calvin backend directory so `app.*` imports resolve:
    cd calvin/backend
    uv run pytest ../../calvin-plugins/sl_departures/test_sl_departures.py
"""

import importlib.util
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

try:
    from app.plugins.definitions import PluginMetadata
    from app.plugins.loader import PluginLoader
    from app.plugins.protocols import ServicePlugin
except ImportError as e:  # pragma: no cover
    pytest.skip(f"Backend dependencies not available: {e}", allow_module_level=True)


def _load_plugin_module():
    plugin_path = Path(__file__).parent / "plugin.py"
    spec = importlib.util.spec_from_file_location("sl_plugin_under_test", plugin_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sl_module = _load_plugin_module()
SLDeparturesServicePlugin = sl_module.SLDeparturesServicePlugin


class TestContractShape:
    def test_discoverable_by_loader(self):
        loader = PluginLoader()
        module = types.ModuleType("installed_plugin_sl_departures")
        module.SLDeparturesServicePlugin = SLDeparturesServicePlugin
        assert loader.register_module(module) == ["sl_departures"]

    def test_no_module_level_hooks(self):
        for hook in (
            "register_plugin_types",
            "create_plugin_instance",
            "handle_plugin_config_update",
        ):
            assert not hasattr(sl_module, hook), hook

    def test_metadata(self):
        md = SLDeparturesServicePlugin.metadata
        assert isinstance(md, PluginMetadata)
        assert md.type_id == "sl_departures"
        assert md.display_schema["kind"] == "status"
        assert md.display_schema["layout"] == "list"
        assert md.statusbar_schema["kind"] == "status"

    def test_is_service_plugin(self):
        assert issubclass(SLDeparturesServicePlugin, ServicePlugin)
