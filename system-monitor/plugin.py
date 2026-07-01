"""System Monitor service plugin — CPU, memory, disk, temperature, network.

Plugin contract 1.0: one declarative class, config declared once in
`metadata.instance_config_schema`, kind-based display/statusbar schemas, and
`fetch()` as the single data verb. The host discovers this class and derives
registration, instantiation, and config handling from `metadata`.

The panel is a built-in `metric-dashboard` over the `metrics` array in the
fetch() payload; the statusbar item is a built-in `status` row over the
`statusbar` array. The plugin ships no frontend code.
"""

import asyncio
import shutil
import subprocess
from typing import Any

from app.plugins.definitions import PluginMetadata
from app.plugins.protocols import ServicePlugin

try:
    import psutil

    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False


# Status thresholds. Temperature levels mirror the retired SystemMonitor.vue
# (>= 60 °C warm, >= 75 °C hot — always compared in Celsius); percent metrics
# (CPU / RAM / disk) use a shared warn/error pair.
_TEMP_WARN_C = 60.0
_TEMP_ERROR_C = 75.0
_PERCENT_WARN = 85.0
_PERCENT_ERROR = 95.0


def _status(value: float | None, warn_at: float, error_at: float) -> str:
    """Map a numeric reading onto the renderer's ok | warn | error scale."""
    if value is None:
        return "ok"
    if value >= error_at:
        return "error"
    if value >= warn_at:
        return "warn"
    return "ok"


def _vcgencmd_temp() -> float | None:
    """Read GPU temperature via vcgencmd (Raspberry Pi only)."""
    if not shutil.which("vcgencmd"):
        return None
    try:
        out = subprocess.check_output(["vcgencmd", "measure_temp"], timeout=2, text=True)
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

    metadata = PluginMetadata(
        type_id="system_monitor",
        name="System Monitor",
        description="Live CPU, memory, disk, temperature and network stats",
        supports_multiple_instances=False,
        # Preserves the pre-1.0 fixed id (default would be "system_monitor-instance").
        fixed_instance_id="system-monitor-instance",
        default_instance_name="System Monitor",
        instance_config_schema={
            "show_temperature": {
                "type": "boolean",
                "description": "Show CPU/GPU temperature",
                "default": True,
                "ui": {"component": "checkbox"},
            },
            "show_network": {
                "type": "boolean",
                "description": "Show network throughput",
                "default": True,
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
        ui_actions=[
            {
                "id": "save",
                "type": "save",
                "label": "Save Settings",
                "style": "primary",
                "scope": "instance",
            },
        ],
        # The fetch() payload feeds the built-in metric-dashboard renderer:
        # one tile per entry in $.metrics, status derived server-side.
        display_schema={
            "kind": "metric-dashboard",
            "data_path": "$.metrics",
            "layout": {"columns": 2},
            "tile": {
                "label_path": "$.label",
                "value_path": "$.value",
                "unit_path": "$.unit",
                "status_path": "$.status",
            },
            "poll_interval_ms": 10000,
        },
        statusbar_schema={
            "kind": "status",
            "data_path": "$.statusbar",
            "item": {
                "label_path": "$.label",
                "value_path": "$.value",
                "unit_path": "$.unit",
                "status_path": "$.status",
            },
            "poll_interval_ms": 30000,
        },
    )

    def __init__(self, plugin_id: str, name: str, enabled: bool = True):
        super().__init__(plugin_id, name, enabled)
        self._net_bytes_prev: tuple[int, int] | None = None

    # Config accessors — values live in self.config (schema-normalized).

    @property
    def show_temperature(self) -> bool:
        return bool(self.config.get("show_temperature", True))

    @property
    def show_network(self) -> bool:
        return bool(self.config.get("show_network", True))

    @property
    def temp_unit(self) -> str:
        return str(self.config.get("temp_unit") or "C").upper()

    async def initialize(self) -> None:
        if _PSUTIL_AVAILABLE and self.show_network:
            counters = psutil.net_io_counters()
            self._net_bytes_prev = (counters.bytes_sent, counters.bytes_recv)

    @classmethod
    async def validate_config(cls, config: dict[str, Any]) -> bool:
        """Only constraint beyond the schema: temp_unit must be C or F."""
        normalized = cls.normalize_config(config)
        return str(normalized.get("temp_unit") or "C").upper() in ("C", "F")

    async def fetch(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Collect live metrics and shape them for the display schemas.

        Returns the raw readings plus two schema-bound arrays:
            metrics:   [{label, value, unit, status}] for the panel tiles
            statusbar: [{label?, value, unit, status}] for the clock bar
        """
        if not _PSUTIL_AVAILABLE:
            return {"error": "psutil is not installed", "metrics": [], "statusbar": []}

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

        # Network throughput (KB transferred since the previous poll)
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

        return self._shape_for_display(data)

    def _shape_for_display(self, data: dict[str, Any]) -> dict[str, Any]:
        """Append the `metrics` and `statusbar` arrays the schemas bind to."""
        cpu = data.get("cpu_percent")
        mem_pct = (data.get("memory") or {}).get("percent")
        disk_pct = (data.get("disk") or {}).get("percent")
        temp = data.get("temperature")
        temp_unit = str(data.get("temp_unit") or "C")
        # Thresholds always compare in Celsius, whatever the display unit.
        temp_c = ((temp - 32) * 5 / 9) if (temp is not None and temp_unit == "F") else temp

        cpu_status = _status(cpu, _PERCENT_WARN, _PERCENT_ERROR)
        mem_status = _status(mem_pct, _PERCENT_WARN, _PERCENT_ERROR)
        disk_status = _status(disk_pct, _PERCENT_WARN, _PERCENT_ERROR)
        temp_status = _status(temp_c, _TEMP_WARN_C, _TEMP_ERROR_C)

        metrics: list[dict[str, Any]] = [
            {"label": "CPU", "value": round(cpu or 0), "unit": "%", "status": cpu_status},
            {"label": "RAM", "value": round(mem_pct or 0), "unit": "%", "status": mem_status},
            {"label": "Disk", "value": round(disk_pct or 0), "unit": "%", "status": disk_status},
        ]
        if temp is not None:
            metrics.append(
                {
                    "label": "Temp",
                    "value": temp,
                    "unit": f"°{temp_unit}",
                    "status": temp_status,
                }
            )
        network = data.get("network")
        if network:
            metrics.append(
                {"label": "Net ↑", "value": network["sent_kbps"], "unit": "KB/s", "status": "ok"}
            )
            metrics.append(
                {"label": "Net ↓", "value": network["recv_kbps"], "unit": "KB/s", "status": "ok"}
            )

        statusbar: list[dict[str, Any]] = [
            {"label": "CPU", "value": round(cpu or 0), "unit": "%", "status": cpu_status},
            {"label": "RAM", "value": round(mem_pct or 0), "unit": "%", "status": mem_status},
        ]
        if temp is not None:
            statusbar.append(
                {"value": temp, "unit": f"°{temp_unit}", "status": temp_status}
            )

        return {**data, "metrics": metrics, "statusbar": statusbar}
