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


@pytest.fixture
async def plugin():
    instance = SLDeparturesServicePlugin(plugin_id="sl-test", name="SL", enabled=True)
    await instance.configure(
        {
            "stop_name": " Tappström ",
            "lines": "176, 177",
            "modes": "bus, Train",
            "direction": "Any",
            "max_departures": "8",
            "forecast_minutes": "60",
        }
    )
    return instance


class TestConfig:
    async def test_accessors_normalize(self, plugin):
        assert plugin.stop_name == "Tappström"
        assert plugin.lines == {"176", "177"}
        assert plugin.modes == {"BUS", "TRAIN"}
        assert plugin.direction == "Any"
        assert plugin.max_departures == 8
        assert plugin.forecast_minutes == 60
        assert plugin.clockbar_show_following is True
        assert plugin.site_id is None  # 0/blank means unset

    async def test_site_id_override(self):
        instance = SLDeparturesServicePlugin("sl-x", "SL")
        await instance.configure({"stop_name": "x", "site_id": "3002"})
        assert instance.site_id == 3002

    async def test_bounds_clamped(self):
        instance = SLDeparturesServicePlugin("sl-x", "SL")
        await instance.configure({"stop_name": "x", "max_departures": 999, "forecast_minutes": 1})
        assert instance.max_departures == 30
        assert instance.forecast_minutes == 5

    async def test_validate_config(self):
        assert await SLDeparturesServicePlugin.validate_config({"stop_name": "Tappström"}) is True
        assert await SLDeparturesServicePlugin.validate_config({"site_id": 3002}) is True
        assert await SLDeparturesServicePlugin.validate_config({"stop_name": "", "site_id": 0}) is False
        assert await SLDeparturesServicePlugin.validate_config({"stop_name": "x", "direction": "9"}) is False
