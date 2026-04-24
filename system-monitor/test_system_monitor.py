"""Tests for System Monitor plugin.

These tests should be run from the backend directory:
    cd backend
    pytest ../calvin-plugins/system-monitor/test_system_monitor.py
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    from app.plugins.base import PluginType

    import importlib.util
    from pathlib import Path

    plugin_path = Path(__file__).parent / "plugin.py"
    if plugin_path.exists():
        spec = importlib.util.spec_from_file_location("system_monitor_plugin", plugin_path)
        if spec and spec.loader:
            system_monitor_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(system_monitor_module)
            SystemMonitorServicePlugin = system_monitor_module.SystemMonitorServicePlugin
        else:
            pytest.skip("Could not load system-monitor plugin module")
    else:
        pytest.skip("system-monitor plugin.py not found")
except ImportError as e:
    pytest.skip(f"Backend dependencies not available: {e}")


@pytest.fixture
def system_monitor_plugin():
    return SystemMonitorServicePlugin(
        plugin_id="system-monitor-instance",
        name="System Monitor",
        show_temperature=True,
        show_network=True,
        temp_unit="C",
        enabled=True,
    )


class TestSystemMonitorServicePlugin:
    def test_get_plugin_metadata(self):
        metadata = SystemMonitorServicePlugin.get_plugin_metadata()
        assert metadata["type_id"] == "system_monitor"
        assert metadata["plugin_type"] == PluginType.SERVICE
        assert metadata["supports_multiple_instances"] is False
        assert metadata["plugin_class"] is SystemMonitorServicePlugin

    @pytest.mark.asyncio
    async def test_get_content(self, system_monitor_plugin):
        content = await system_monitor_plugin.get_content()
        assert content["type"] == "system_monitor"
        assert content["url"] == "/api/plugins/system-monitor-instance/data"

    @pytest.mark.asyncio
    async def test_configure(self, system_monitor_plugin):
        await system_monitor_plugin.configure(
            {
                "show_temperature": False,
                "show_network": False,
                "temp_unit": "F",
            }
        )

        assert system_monitor_plugin.show_temperature is False
        assert system_monitor_plugin.show_network is False
        assert system_monitor_plugin.temp_unit == "F"

    @pytest.mark.asyncio
    async def test_fetch_service_data_without_psutil(self, system_monitor_plugin):
        with patch.object(system_monitor_module, "_PSUTIL_AVAILABLE", False):
            result = await system_monitor_plugin.fetch_service_data()

        assert result == {"error": "psutil is not installed"}

    @pytest.mark.asyncio
    async def test_fetch_service_data_with_metrics(self, system_monitor_plugin):
        fake_psutil = MagicMock()
        fake_psutil.cpu_percent.return_value = 12.5
        fake_psutil.cpu_count.return_value = 8
        fake_psutil.virtual_memory.return_value = MagicMock(
            total=1024**3, used=512 * 1024**2, percent=50
        )
        fake_psutil.disk_usage.return_value = MagicMock(
            total=128 * 1024**3,
            used=64 * 1024**3,
            percent=50,
        )
        fake_psutil.net_io_counters.side_effect = [
            MagicMock(bytes_sent=1000, bytes_recv=2000),
            MagicMock(bytes_sent=3000, bytes_recv=5000),
        ]

        with (
            patch.object(system_monitor_module, "_PSUTIL_AVAILABLE", True),
            patch.object(system_monitor_module, "psutil", fake_psutil, create=True),
            patch("asyncio.get_event_loop") as get_event_loop,
        ):
            loop = MagicMock()
            loop.run_in_executor = AsyncMock(return_value=42.0)
            get_event_loop.return_value = loop
            await system_monitor_plugin.initialize()
            data = await system_monitor_plugin.fetch_service_data()

        assert data["cpu_percent"] == 12.5
        assert data["cpu_count"] == 8
        assert data["memory"]["percent"] == 50
        assert data["disk"]["percent"] == 50
        assert data["temperature"] == 42.0
        assert data["network"]["sent_kbps"] == 2.0
        assert data["network"]["recv_kbps"] == 2.9
