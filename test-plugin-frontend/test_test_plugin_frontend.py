"""Tests for Test Plugin with Frontend.

These tests should be run from the backend directory:
    cd backend
    pytest ../calvin-plugins/test-plugin-frontend/test_test_plugin_frontend.py
"""

import pytest

try:
    from app.plugins.base import PluginType

    import importlib.util
    from pathlib import Path

    plugin_path = Path(__file__).parent / "plugin.py"
    if plugin_path.exists():
        spec = importlib.util.spec_from_file_location("test_plugin_frontend_plugin", plugin_path)
        if spec and spec.loader:
            frontend_plugin_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(frontend_plugin_module)
            _PluginClass = frontend_plugin_module.TestFrontendServicePlugin
        else:
            pytest.skip("Could not load test-plugin-frontend plugin module")
    else:
        pytest.skip("test-plugin-frontend plugin.py not found")
except ImportError as e:
    pytest.skip(f"Backend dependencies not available: {e}")


@pytest.fixture
def frontend_plugin():
    return _PluginClass(
        plugin_id="test-plugin-frontend-instance",
        name="Test Plugin with Frontend",
        message="Frontend test message",
        enabled=True,
    )


class TestTestFrontendServicePlugin:
    def test_get_plugin_metadata(self):
        metadata = _PluginClass.get_plugin_metadata()
        assert metadata["type_id"] == "test_plugin_frontend"
        assert metadata["plugin_type"] == PluginType.SERVICE
        assert metadata["plugin_class"] is _PluginClass

    @pytest.mark.asyncio
    async def test_get_content(self, frontend_plugin):
        content = await frontend_plugin.get_content()
        assert content["type"] == "iframe"
        assert content["url"] == "about:blank"
        assert content["config"]["message"] == "Frontend test message"

    @pytest.mark.asyncio
    async def test_validate_config(self, frontend_plugin):
        assert await frontend_plugin.validate_config({}) is True
