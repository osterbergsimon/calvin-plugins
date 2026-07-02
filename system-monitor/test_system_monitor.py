"""Tests for the System Monitor plugin (plugin contract 1.0).

Run from the calvin backend directory so `app.*` imports resolve:
    cd calvin/backend
    uv run pytest ../../calvin-plugins/system-monitor/test_system_monitor.py

psutil is deliberately NOT required: the plugin module guards its import, and
these tests mock psutil at the module boundary.
"""

import importlib.util
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

try:
    from app.plugins.definitions import PluginMetadata
    from app.plugins.loader import PluginLoader
    from app.plugins.protocols import ServicePlugin
except ImportError as e:  # pragma: no cover
    pytest.skip(f"Backend dependencies not available: {e}", allow_module_level=True)


def _load_plugin_module():
    plugin_path = Path(__file__).parent / "plugin.py"
    spec = importlib.util.spec_from_file_location(
        "system_monitor_plugin_under_test", plugin_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sysmon_module = _load_plugin_module()
SystemMonitorServicePlugin = sysmon_module.SystemMonitorServicePlugin


@pytest.fixture
async def plugin():
    """A configured plugin instance."""
    instance = SystemMonitorServicePlugin(
        plugin_id="system-monitor-instance", name="System Monitor", enabled=True
    )
    await instance.configure(
        {
            "show_temperature": "true",
            "show_network": True,
            "temp_unit": "C",
            "show_in_statusbar": "1",
        }
    )
    return instance


class TestContractShape:
    """The plugin conforms to contract 1.0: one class, declarative metadata."""

    def test_discoverable_by_loader(self):
        loader = PluginLoader()
        module = types.ModuleType("installed_plugin_system_monitor")
        module.SystemMonitorServicePlugin = SystemMonitorServicePlugin
        assert loader.register_module(module) == ["system_monitor"]

    def test_no_module_level_hooks(self):
        for hook in (
            "register_plugin_types",
            "create_plugin_instance",
            "handle_plugin_config_update",
        ):
            assert not hasattr(sysmon_module, hook), hook

    def test_metadata(self):
        md = SystemMonitorServicePlugin.metadata
        assert isinstance(md, PluginMetadata)
        assert md.type_id == "system_monitor"
        # Single-instance semantics with the pre-1.0 fixed id preserved.
        assert md.supports_multiple_instances is False
        assert md.fixed_instance_id == "system-monitor-instance"
        assert md.display_schema["kind"] == "metric-dashboard"
        assert md.display_schema["data_path"] == "$.metrics"
        assert md.statusbar_schema["kind"] == "status"
        assert md.statusbar_schema["data_path"] == "$.statusbar"
        assert "show_in_statusbar" in md.instance_config_schema

    def test_is_service_plugin(self):
        assert issubclass(SystemMonitorServicePlugin, ServicePlugin)


class TestConfig:
    async def test_config_normalization_and_accessors(self, plugin):
        assert plugin.show_temperature is True  # "true" converted by schema type
        assert plugin.show_network is True
        assert plugin.temp_unit == "C"
        assert plugin.config["show_in_statusbar"] is True  # "1" converted

    async def test_defaults_apply(self):
        instance = SystemMonitorServicePlugin("sm-x", "System Monitor")
        await instance.configure({})
        assert instance.show_temperature is True
        assert instance.show_network is True
        assert instance.temp_unit == "C"
        assert instance.config["show_in_statusbar"] is False

    async def test_validate_config(self):
        assert await SystemMonitorServicePlugin.validate_config({}) is True
        assert await SystemMonitorServicePlugin.validate_config({"temp_unit": "F"}) is True
        assert await SystemMonitorServicePlugin.validate_config({"temp_unit": "K"}) is False


class TestThresholds:
    """Status derivation matches the retired SystemMonitor.vue thresholds."""

    def test_status_helper(self):
        _status = sysmon_module._status
        assert _status(None, 85, 95) == "ok"
        assert _status(84.9, 85, 95) == "ok"
        assert _status(85, 85, 95) == "warn"
        assert _status(94.9, 85, 95) == "warn"
        assert _status(95, 85, 95) == "error"

    def test_temperature_thresholds_in_celsius(self):
        instance = SystemMonitorServicePlugin("sm-x", "System Monitor")
        base = {"cpu_percent": 10, "memory": {"percent": 10}, "disk": {"percent": 10}}

        def temp_status(temperature, unit):
            shaped = instance._shape_for_display(
                {**base, "temperature": temperature, "temp_unit": unit}
            )
            return next(m for m in shaped["metrics"] if m["label"] == "Temp")["status"]

        assert temp_status(59.9, "C") == "ok"
        assert temp_status(60.0, "C") == "warn"
        assert temp_status(75.0, "C") == "error"
        # Fahrenheit readings convert back to Celsius before comparison:
        # 167 °F == 75 °C -> error.
        assert temp_status(167.0, "F") == "error"
        assert temp_status(140.0, "F") == "warn"  # 60 °C
        assert temp_status(100.0, "F") == "ok"  # ~37.8 °C


class TestFetchShaping:
    """fetch() output binds to the metric-dashboard and status schemas."""

    def test_shape_builds_metrics_and_statusbar(self):
        instance = SystemMonitorServicePlugin("sm-x", "System Monitor")
        shaped = instance._shape_for_display(
            {
                "cpu_percent": 90.0,
                "memory": {"percent": 96.0},
                "disk": {"percent": 50.0},
                "temperature": 42.0,
                "temp_unit": "C",
                "network": {"sent_kbps": 2.0, "recv_kbps": 2.9},
            }
        )
        by_label = {m["label"]: m for m in shaped["metrics"]}
        assert by_label["CPU"]["status"] == "warn"
        assert by_label["RAM"]["status"] == "error"
        assert by_label["Disk"]["status"] == "ok"
        assert by_label["Temp"] == {
            "label": "Temp",
            "value": 42.0,
            "unit": "°C",
            "status": "ok",
        }
        assert by_label["Net ↑"]["value"] == 2.0
        assert by_label["Net ↓"]["value"] == 2.9

        assert [item.get("label") for item in shaped["statusbar"]] == ["CPU", "RAM", None]
        assert shaped["statusbar"][2]["unit"] == "°C"

    def test_shape_omits_absent_readings(self):
        instance = SystemMonitorServicePlugin("sm-x", "System Monitor")
        shaped = instance._shape_for_display(
            {"cpu_percent": 10, "memory": {"percent": 10}, "disk": {"percent": 10}}
        )
        labels = [m["label"] for m in shaped["metrics"]]
        assert labels == ["CPU", "RAM", "Disk"]
        assert len(shaped["statusbar"]) == 2

    async def test_fetch_without_psutil(self, plugin):
        with patch.object(sysmon_module, "_PSUTIL_AVAILABLE", False):
            result = await plugin.fetch()
        assert result["error"] == "psutil is not installed"
        assert result["metrics"] == []
        assert result["statusbar"] == []

    async def test_fetch_with_metrics(self, plugin):
        fake_psutil = MagicMock()
        fake_psutil.cpu_percent.return_value = 12.5
        fake_psutil.cpu_count.return_value = 8
        fake_psutil.virtual_memory.return_value = MagicMock(
            total=1024**3, used=512 * 1024**2, percent=50
        )
        fake_psutil.disk_usage.return_value = MagicMock(
            total=128 * 1024**3, used=64 * 1024**3, percent=50
        )
        fake_psutil.net_io_counters.side_effect = [
            MagicMock(bytes_sent=1000, bytes_recv=2000),
            MagicMock(bytes_sent=3000, bytes_recv=5000),
        ]

        with (
            patch.object(sysmon_module, "_PSUTIL_AVAILABLE", True),
            patch.object(sysmon_module, "psutil", fake_psutil, create=True),
            patch.object(sysmon_module, "_cpu_temp", lambda: 42.0),
        ):
            await plugin.initialize()
            data = await plugin.fetch()

        # Raw readings survive alongside the shaped arrays.
        assert data["cpu_percent"] == 12.5
        assert data["cpu_count"] == 8
        assert data["memory"]["percent"] == 50
        assert data["disk"]["percent"] == 50
        assert data["temperature"] == 42.0
        assert data["network"]["sent_kbps"] == 2.0
        assert data["network"]["recv_kbps"] == 2.9

        labels = [m["label"] for m in data["metrics"]]
        assert labels == ["CPU", "RAM", "Disk", "Temp", "Net ↑", "Net ↓"]
        assert all(m["status"] == "ok" for m in data["metrics"])

    async def test_fetch_converts_to_fahrenheit(self):
        instance = SystemMonitorServicePlugin("sm-x", "System Monitor")
        await instance.configure({"temp_unit": "F", "show_network": False})

        fake_psutil = MagicMock()
        fake_psutil.cpu_percent.return_value = 10.0
        fake_psutil.cpu_count.return_value = 4
        fake_psutil.virtual_memory.return_value = MagicMock(
            total=1024**3, used=1024**2, percent=10
        )
        fake_psutil.disk_usage.return_value = MagicMock(
            total=1024**3, used=1024**2, percent=10
        )

        with (
            patch.object(sysmon_module, "_PSUTIL_AVAILABLE", True),
            patch.object(sysmon_module, "psutil", fake_psutil, create=True),
            patch.object(sysmon_module, "_cpu_temp", lambda: 80.0),
        ):
            data = await instance.fetch()

        assert data["temperature"] == 176.0  # 80 °C
        assert data["temp_unit"] == "F"
        temp_tile = next(m for m in data["metrics"] if m["label"] == "Temp")
        assert temp_tile["unit"] == "°F"
        assert temp_tile["status"] == "error"  # threshold compared in Celsius
        assert "network" not in data
