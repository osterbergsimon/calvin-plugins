"""Tests for Chromecast plugin.

These tests should be run from the backend directory:
    cd backend
    pytest ../calvin-plugins/chromecast/test_chromecast.py
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    from app.plugins.base import PluginType

    import importlib.util
    from pathlib import Path

    plugin_path = Path(__file__).parent / "plugin.py"
    if plugin_path.exists():
        spec = importlib.util.spec_from_file_location("chromecast_plugin", plugin_path)
        if spec and spec.loader:
            chromecast_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(chromecast_module)
            ChromecastServicePlugin = chromecast_module.ChromecastServicePlugin
        else:
            pytest.skip("Could not load chromecast plugin module")
    else:
        pytest.skip("chromecast plugin.py not found")
except ImportError as e:
    pytest.skip(f"Backend dependencies not available: {e}")


class TestChromecastServicePlugin:
    def test_get_plugin_metadata(self):
        metadata = ChromecastServicePlugin.get_plugin_metadata()
        assert metadata["type_id"] == "chromecast"
        assert metadata["plugin_type"] == PluginType.SERVICE
        assert metadata["supports_multiple_instances"] is True

    @pytest.mark.asyncio
    async def test_scan_type_options_ignores_other_fields(self):
        assert await ChromecastServicePlugin.scan_type_options("other_field") is None

    @pytest.mark.asyncio
    async def test_scan_type_options_without_dependency(self):
        with patch.object(chromecast_module, "_PYCHROMECAST_AVAILABLE", False):
            result = await ChromecastServicePlugin.scan_type_options("device_name")

        assert result == {"options": [], "error": "pychromecast is not installed"}

    @pytest.mark.asyncio
    async def test_scan_type_options_discovers_devices(self):
        fake_cast = MagicMock()
        fake_cast.cast_info.friendly_name = "Living Room"
        fake_browser = object()
        fake_pychromecast = MagicMock()
        fake_pychromecast.get_chromecasts.return_value = ([fake_cast], fake_browser)

        with (
            patch.object(chromecast_module, "_PYCHROMECAST_AVAILABLE", True),
            patch.object(chromecast_module, "pychromecast", fake_pychromecast),
            patch("asyncio.get_event_loop") as get_event_loop,
        ):
            loop = MagicMock()
            loop.run_in_executor = AsyncMock(side_effect=lambda executor, func: func())
            get_event_loop.return_value = loop

            result = await ChromecastServicePlugin.scan_type_options("device_name")

        assert result == {"options": [{"value": "Living Room", "label": "Living Room"}]}
