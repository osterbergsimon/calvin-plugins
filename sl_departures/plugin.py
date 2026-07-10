"""SL Departures service plugin — live SL public-transport board for one stop.

Calvin plugin contract 1.0: one declarative class, config declared once in
`metadata.instance_config_schema`, `fetch()` as the single data verb, and the
built-in `status` renderer for both the panel (list) and the clock-bar strip.
Backed by the keyless SL Transport API (https://transport.integration.sl.se).
"""

from typing import Any

import httpx
from loguru import logger

from app.plugins.definitions import PluginMetadata
from app.plugins.protocols import ServicePlugin


class SLDeparturesServicePlugin(ServicePlugin):
    """Service plugin showing SL departures for a single stop."""

    BASE_URL = "https://transport.integration.sl.se"

    metadata = PluginMetadata(
        type_id="sl_departures",
        name="SL Departures",
        description="Live SL departures for a Stockholm stop, filterable by line, mode and direction",
        default_instance_name="SL Departures",
        instance_label="Stop",
        supports_multiple_instances=True,
        instance_config_schema={
            "stop_name": {
                "type": "string",
                "description": "Stop name (resolved to a site id on Test Connection)",
                "default": "",
                "ui": {
                    "component": "input",
                    "placeholder": "Tappström",
                    "validation": {"required": True},
                },
            },
            "site_id": {
                "type": "integer",
                "description": "SL site id (auto-filled after Test; wins over stop name if set)",
                "default": 0,
                "ui": {
                    "component": "number",
                    "placeholder": "auto-filled after Test",
                    "help_text": "Leave blank unless the stop name is ambiguous",
                },
            },
            "lines": {
                "type": "string",
                "description": "Only show these lines (comma-separated). Empty = all lines.",
                "default": "",
                "ui": {"component": "input", "placeholder": "176, 177"},
            },
            "modes": {
                "type": "string",
                "description": "Only show these modes (comma-separated): bus, metro, train, tram, ship. Empty = all.",
                "default": "",
                "ui": {"component": "input", "placeholder": "bus, train"},
            },
            "direction": {
                "type": "string",
                "description": "Filter by SL direction code",
                "default": "Any",
                "ui": {
                    "component": "select",
                    "options": [
                        {"value": "Any", "label": "Any direction"},
                        {"value": "1", "label": "Direction 1"},
                        {"value": "2", "label": "Direction 2"},
                    ],
                    "help_text": "SL's direction codes are arbitrary per line; usually leave Any and filter by line",
                },
            },
            "max_departures": {
                "type": "integer",
                "description": "Maximum rows on the panel",
                "default": 8,
                "ui": {"component": "number", "placeholder": "8", "validation": {"min": 1, "max": 30}},
            },
            "forecast_minutes": {
                "type": "integer",
                "description": "How far ahead to look (minutes)",
                "default": 60,
                "ui": {"component": "number", "placeholder": "60", "validation": {"min": 5, "max": 180}},
            },
            "clockbar_show_following": {
                "type": "boolean",
                "description": "Clock bar shows the departure after next as well",
                "default": True,
                "ui": {"component": "checkbox", "help_text": "Off = clock bar shows only the next departure"},
            },
        },
        ui_actions=[
            {"id": "save", "type": "save", "label": "Save Settings", "style": "primary", "scope": "instance"},
            {"id": "test", "type": "test", "label": "Test Connection", "style": "secondary", "scope": "instance"},
        ],
        # Panel: one row per departure, drawn by the built-in status list renderer.
        display_schema={
            "kind": "status",
            "layout": "list",
            "data_path": "$.departures",
            "item": {
                "label_path": "$.label",
                "value_path": "$.display",
                "status_path": "$.status",
            },
            "poll_interval_ms": 30000,
        },
        # Clock bar: stop name + next (and optionally following) departure.
        statusbar_schema={
            "kind": "status",
            "item": {
                "label_path": "$.clockbar.label",
                "value_path": "$.clockbar.value",
                "status_path": "$.clockbar.status",
            },
            "poll_interval_ms": 30000,
        },
    )

    def __init__(self, plugin_id: str, name: str, enabled: bool = True):
        super().__init__(plugin_id, name, enabled)

    async def fetch(self, start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
        return {"departures": [], "clockbar": {"label": "", "value": "—", "status": "ok"}}
