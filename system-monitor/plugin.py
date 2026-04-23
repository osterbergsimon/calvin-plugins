"""System Monitor service plugin — CPU, memory, disk, temperature, network."""

import asyncio
import shutil
import subprocess
from typing import Any

from app.plugins.base import PluginType
from app.plugins.hooks import hookimpl
from app.plugins.protocols import ServicePlugin
from app.plugins.utils.config import extract_config_value, to_bool, to_str
from app.plugins.utils.instance_manager import (
    InstanceManagerConfig,
    handle_plugin_config_update_generic,
)

try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False


def _vcgencmd_temp() -> float | None:
    """Read GPU temperature via vcgencmd (Raspberry Pi only)."""
    if not shutil.which("vcgencmd"):
        return None
    try:
        out = subprocess.check_output(
            ["vcgencmd", "measure_temp"], timeout=2, text=True
        )
        # output: "temp=42.8'C"
        return float(out.strip().split("=")[1].replace("'C", ""))
    except Exception:
        return None


def _cpu_temp() -> float | None:
    """Return CPU temperature in °C, preferring vcgencmd on Pi."""
    pi_temp = _vcgencmd_temp()
    if pi_temp is not None:
        return pi_temp
    if not _PSUTIL_AVAILABLE:
        return None
    temps = psutil.sensors_temperatures() if hasattr(psutil, "sensors_temperatures") else {}
    for key in ("cpu_thermal", "coretemp", "k10temp", "acpitz"):
        entries = temps.get(key, [])
        if entries:
            return entries[0].current
    return None


class SystemMonitorServicePlugin(ServicePlugin):
    """Service plugin that exposes live system metrics to the dashboard."""

    @classmethod
    def get_plugin_metadata(cls) -> dict[str, Any]:
        return {
            "type_id": "system_monitor",
            "plugin_type": PluginType.SERVICE,
            "name": "System Monitor",
            "description": "Live CPU, memory, disk, temperature and network stats",
            "version": "1.0.0",
            "supports_multiple_instances": False,
            "common_config_schema": {
                "show_temperature": {
                    "type": "boolean",
                    "description": "Show CPU/GPU temperature",
                    "default": "true",
                    "ui": {"component": "checkbox"},
                },
                "show_network": {
                    "type": "boolean",
                    "description": "Show network throughput",
                    "default": "true",
                    "ui": {"component": "checkbox"},
                },
                "temp_unit": {
                    "type": "string",
                    "description": "Temperature unit",
                    "default": "C",
                    "ui": {
                        "component": "select",
                        "options": [
                            {"value": "C", "label": "Celsius (°C)"},
                            {"value": "F", "label": "Fahrenheit (°F)"},
                        ],
                    },
                },
                "show_in_statusbar": {
                    "type": "boolean",
                    "description": "Show CPU/RAM summary in the clock bar",
                    "default": False,
                    "ui": {"component": "checkbox"},
                },
            },
            "instance_config_schema": {},
            "display_schema": {
                "component": "system_monitor/SystemMonitor.vue",
            },
            "statusbar_schema": {
                "component": "system_monitor/SystemStatusbar.vue",
            },
            "plugin_class": cls,
        }

    def __init__(
        self,
        plugin_id: str,
        name: str,
        show_temperature: bool = True,
        show_network: bool = True,
        temp_unit: str = "C",
        enabled: bool = True,
    ):
        super().__init__(plugin_id, name, enabled)
        self.show_temperature = show_temperature
        self.show_network = show_network
        self.temp_unit = temp_unit
        self._net_bytes_prev: tuple[int, int] | None = None

    async def initialize(self) -> None:
        if _PSUTIL_AVAILABLE and self.show_network:
            counters = psutil.net_io_counters()
            self._net_bytes_prev = (counters.bytes_sent, counters.bytes_recv)

    async def cleanup(self) -> None:
        pass

    async def get_content(self) -> dict[str, Any]:
        return {
            "type": "system_monitor",
            "url": f"/api/plugins/{self.plugin_id}/data",
            "config": {
                "show_temperature": self.show_temperature,
                "show_network": self.show_network,
                "temp_unit": self.temp_unit,
            },
        }

    def get_config(self) -> dict[str, Any]:
        return {
            "url": f"/api/plugins/{self.plugin_id}/data",
            "show_temperature": self.show_temperature,
            "show_network": self.show_network,
            "temp_unit": self.temp_unit,
        }

    async def fetch_service_data(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        if not _PSUTIL_AVAILABLE:
            return {"error": "psutil is not installed"}

        data: dict[str, Any] = {}

        # CPU
        data["cpu_percent"] = psutil.cpu_percent(interval=0.2)
        data["cpu_count"] = psutil.cpu_count(logical=True)

        # Memory
        mem = psutil.virtual_memory()
        data["memory"] = {
            "total_mb": round(mem.total / 1024 / 1024),
            "used_mb": round(mem.used / 1024 / 1024),
            "percent": mem.percent,
        }

        # Disk (root)
        disk = psutil.disk_usage("/")
        data["disk"] = {
            "total_gb": round(disk.total / 1024 / 1024 / 1024, 1),
            "used_gb": round(disk.used / 1024 / 1024 / 1024, 1),
            "percent": disk.percent,
        }

        # Temperature
        if self.show_temperature:
            temp_c = await asyncio.get_event_loop().run_in_executor(None, _cpu_temp)
            if temp_c is not None:
                if self.temp_unit == "F":
                    data["temperature"] = round(temp_c * 9 / 5 + 32, 1)
                else:
                    data["temperature"] = round(temp_c, 1)
                data["temp_unit"] = self.temp_unit

        # Network throughput
        if self.show_network:
            counters = psutil.net_io_counters()
            current = (counters.bytes_sent, counters.bytes_recv)
            if self._net_bytes_prev:
                prev = self._net_bytes_prev
                data["network"] = {
                    "sent_kbps": round((current[0] - prev[0]) / 1024, 1),
                    "recv_kbps": round((current[1] - prev[1]) / 1024, 1),
                }
            self._net_bytes_prev = current

        return data

    async def validate_config(self, config: dict[str, Any]) -> bool:
        return True

    async def configure(self, config: dict[str, Any]) -> None:
        await super().configure(config)
        self.show_temperature = extract_config_value(config, "show_temperature", default=True, converter=to_bool)
        self.show_network = extract_config_value(config, "show_network", default=True, converter=to_bool)
        self.temp_unit = extract_config_value(config, "temp_unit", default="C", converter=to_str)


@hookimpl
def register_plugin_types() -> list[dict[str, Any]]:
    return [SystemMonitorServicePlugin.get_plugin_metadata()]


@hookimpl
def create_plugin_instance(
    plugin_id: str,
    type_id: str,
    name: str,
    config: dict[str, Any],
) -> SystemMonitorServicePlugin | None:
    if type_id != "system_monitor":
        return None
    return SystemMonitorServicePlugin(
        plugin_id=plugin_id,
        name=name,
        show_temperature=extract_config_value(config, "show_temperature", default=True, converter=to_bool),
        show_network=extract_config_value(config, "show_network", default=True, converter=to_bool),
        temp_unit=extract_config_value(config, "temp_unit", default="C", converter=to_str),
        enabled=config.get("enabled", False),
    )


@hookimpl
async def handle_plugin_config_update(
    type_id: str,
    config: dict[str, Any],
    enabled: bool | None,
    db_type: Any,
    session: Any,
) -> dict[str, Any] | None:
    if type_id != "system_monitor":
        return None

    def normalize_config(c: dict[str, Any]) -> dict[str, Any]:
        return {
            "show_temperature": extract_config_value(c, "show_temperature", default=True, converter=to_bool),
            "show_network": extract_config_value(c, "show_network", default=True, converter=to_bool),
            "temp_unit": extract_config_value(c, "temp_unit", default="C", converter=to_str),
            "show_in_statusbar": extract_config_value(c, "show_in_statusbar", default=False, converter=to_bool),
        }

    manager_config = InstanceManagerConfig(
        type_id="system_monitor",
        single_instance=True,
        instance_id="system-monitor-instance",
        normalize_config=normalize_config,
        default_instance_name="System Monitor",
    )

    return await handle_plugin_config_update_generic(
        type_id, config, enabled, db_type, session, manager_config
    )
