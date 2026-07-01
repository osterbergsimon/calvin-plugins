#!/usr/bin/env python3
"""
Scaffold a new Calvin plugin (plugin contract 1.0).

Usage:
    python scripts/create_plugin.py <type> <id> [options]

Types:
    service   - Display data from an API or web service
    image     - Provide images from an external source
    calendar  - Provide calendar events
    backend   - Background task / event handler

Arguments:
    type      Plugin type (service, image, calendar, backend)
    id        Plugin ID — lowercase, hyphens/underscores (e.g. my-weather)

Options:
    --name NAME           Human-readable name (default: title-cased id)
    --description DESC    Short description
    --single              Single-instance plugin (default: multi)
    --label LABEL         Instance label shown in UI (e.g. Location, Device)
    --author AUTHOR       Author name
    --no-tests            Skip generating test file

A 1.0 plugin is ONE class with a `metadata = PluginMetadata(...)` attribute
plus a plugin.json declaring `api_version`. There are no registration hooks:
the host discovers the class, generates the settings form from
`instance_config_schema`, normalizes config into `self.config`, and (for
service plugins) draws the panel from `display_schema` using a built-in
renderer.

Examples:
    python scripts/create_plugin.py service yr-pro --name "Yr.no Pro" --label Location
    python scripts/create_plugin.py image flickr --name Flickr --description "Photos from Flickr"
    python scripts/create_plugin.py backend resize-worker --single
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

PLUGIN_CLASS_MAP = {
    "service": "ServicePlugin",
    "image": "ImagePlugin",
    "calendar": "CalendarPlugin",
    "backend": "BackendPlugin",
}

# Types that default to single-instance
DEFAULT_SINGLE = {"image", "system"}
DEFAULT_INSTANCE_LABELS = {
    "service": "Service",
    "calendar": "Calendar",
    "backend": "Job",
}


def to_class_name(plugin_id: str) -> str:
    """Convert my-plugin or my_plugin to MyPlugin."""
    return "".join(part.title() for part in plugin_id.replace("-", "_").split("_"))


def to_type_id(plugin_id: str) -> str:
    """Normalise to snake_case type_id."""
    return plugin_id.replace("-", "_")


def generate_plugin_json(plugin_id, name, plugin_type, description, author):
    manifest = {
        "api_version": 1,
        "id": to_type_id(plugin_id),
        "name": name,
        "version": "1.0.0",
        "type": plugin_type,
        "description": description,
        "author": author,
        "license": "MIT",
    }
    return json.dumps(manifest, indent=2) + "\n"


def _family_method_lines(plugin_type: str) -> list[str]:
    """Lines for the family-specific methods (verbs) of the plugin class."""
    if plugin_type == "service":
        return [
            "    async def fetch(",
            "        self, start_date: str | None = None, end_date: str | None = None",
            "    ) -> dict[str, Any]:",
            '        """Return the payload the display_schema binds to."""',
            "        # TODO: fetch real data (self.config holds the instance settings)",
            '        return {"message": "hello from " + self.plugin_id}',
        ]
    if plugin_type == "image":
        return [
            "    async def get_images(self) -> list[dict[str, Any]]:",
            "        # TODO: return image metadata dicts (id, filename, path, ...)",
            "        return []",
            "",
            "    async def get_image(self, image_id: str) -> dict[str, Any] | None:",
            "        return None",
            "",
            "    async def get_image_data(self, image_id: str) -> bytes | None:",
            "        return None",
            "",
            "    async def scan_images(self) -> list[dict[str, Any]]:",
            "        return []",
        ]
    if plugin_type == "calendar":
        return [
            "    async def fetch_events(",
            "        self, start_date: datetime, end_date: datetime",
            "    ) -> list[CalendarEvent]:",
            '        """Fetch events overlapping [start_date, end_date] (timezone-aware)."""',
            "        # TODO: fetch and map to CalendarEvent",
            "        return []",
        ]
    # backend
    return [
        "    # Backend plugins are headless. Uncomment what you need:",
        "    #",
        "    # async def get_schedule_config(self) -> dict[str, Any] | None:",
        '    #     return {"interval": 300, "enabled": True}',
        "    #",
        "    # async def run_scheduled_task(self) -> dict[str, Any]:",
        '    #     return {"success": True}',
        "    #",
        "    # async def get_subscribed_events(self) -> list[str]:",
        '    #     return ["image_uploaded"]',
        "    #",
        "    # async def handle_event(self, event_type, event_data):",
        "    #     return None",
    ]


def _display_schema_lines(plugin_type: str) -> list[str]:
    """display_schema/statusbar_schema metadata lines (service plugins only)."""
    if plugin_type != "service":
        return []
    return [
        "        # How the panel is drawn — a built-in renderer, no frontend code.",
        "        # Kinds: status, card-grid, item-list, iframe, image-with-caption,",
        "        # metric-dashboard, weather-forecast, web-component.",
        "        display_schema={",
        '            "kind": "status",',
        '            "item": {"label": "Message", "value_path": "$.message"},',
        '            "poll_interval_ms": 60000,',
        "        },",
        "        # Optional item in the clock bar (kinds: status):",
        '        # statusbar_schema={"kind": "status", "item": {"value_path": "$.message"}},',
    ]


def generate_plugin_py(plugin_id, name, plugin_type, description, single_instance, instance_label):
    cn = to_class_name(plugin_id) + PLUGIN_CLASS_MAP[plugin_type].replace("Plugin", "")
    tid = to_type_id(plugin_id)
    protocol = PLUGIN_CLASS_MAP[plugin_type]

    lines = [
        f'"""{name} plugin."""',
        "",
    ]
    if plugin_type == "calendar":
        lines += ["from datetime import datetime", ""]
    lines += [
        "from typing import Any",
        "",
    ]
    if plugin_type == "calendar":
        lines += ["from app.models.calendar import CalendarEvent"]
    lines += [
        "from app.plugins.definitions import PluginMetadata",
        f"from app.plugins.protocols import {protocol}",
        "",
        "",
        f"class {cn}({protocol}):",
        f'    """{description}"""',
        "",
        "    metadata = PluginMetadata(",
        f'        type_id="{tid}",',
        f'        name="{name}",',
        f'        description="{description}",',
        f'        default_instance_name="{name}",',
    ]

    if single_instance:
        lines += [
            "        supports_multiple_instances=False,",
            f'        fixed_instance_id="{tid}-instance",',
        ]
    else:
        if instance_label:
            lines.append(f'        instance_label="{instance_label}",')
        lines += [
            "        # Config keys that identify an instance (same values -> same",
            "        # instance). TODO: set to your natural identity, e.g. [\"url\"].",
            "        # instance_identity=[\"url\"],",
        ]

    lines += [
        "        # Config is declared ONCE, here. The host generates the settings",
        "        # form, normalizes values by type, and fills self.config.",
        "        instance_config_schema={",
        "            # TODO: add your config fields",
        '            # "url": {',
        '            #     "type": "string",  # string | password | integer | number | boolean',
        '            #     "description": "Server URL",',
        '            #     "default": "",',
        '            #     "ui": {"component": "input", "validation": {"required": True}},',
        "            # },",
        "        },",
    ]
    lines += _display_schema_lines(plugin_type)
    lines += [
        "    )",
        "",
        "    async def initialize(self) -> None:",
        '        """Connect/validate. self.config holds normalized instance config."""',
        "",
        "    async def cleanup(self) -> None:",
        '        """Release resources (close clients, etc.)."""',
        "",
    ]
    lines += _family_method_lines(plugin_type)
    lines += [
        "",
        "    # Optional extras (delete if unused):",
        "    #",
        "    # @classmethod",
        "    # async def validate_config(cls, config: dict[str, Any]) -> bool:",
        '    #     """Extra rules beyond schema-required fields."""',
        "    #     normalized = cls.normalize_config(config)",
        '    #     return str(normalized.get("url", "")).startswith("http")',
        "    #",
        "    # @classmethod",
        "    # async def test_connection(cls, config: dict[str, Any]) -> dict[str, Any] | None:",
        '    #     """Power a \\"Test Connection\\" button (declare a ui_action type=\\"test\\")."""',
        '    #     return {"success": True, "message": "OK"}',
        "",
    ]

    return "\n".join(lines)


def generate_test_py(plugin_id, name, plugin_type):
    cn = to_class_name(plugin_id) + PLUGIN_CLASS_MAP[plugin_type].replace("Plugin", "")
    tid = to_type_id(plugin_id)

    lines = [
        f'"""Tests for {name} (plugin contract 1.0).',
        "",
        "Run from the calvin backend directory:",
        f"    cd calvin/backend && uv run pytest ../../calvin-plugins/{plugin_id}/test_{tid}.py",
        '"""',
        "",
        "import importlib.util",
        "import types",
        "from pathlib import Path",
        "",
        "import pytest",
        "",
        "from app.plugins.definitions import PluginMetadata",
        "from app.plugins.loader import PluginLoader",
        "",
        '_spec = importlib.util.spec_from_file_location("' + tid + '", Path(__file__).parent / "plugin.py")',
        "_mod = importlib.util.module_from_spec(_spec)",
        "_spec.loader.exec_module(_mod)",
        f"{cn} = _mod.{cn}",
        "",
        "",
        "@pytest.fixture",
        "def plugin():",
        f'    return {cn}(plugin_id="test", name="Test", enabled=True)',
        "",
        "",
        f"class Test{cn}:",
        "    def test_discoverable_by_loader(self):",
        '        module = types.ModuleType("installed_plugin_' + tid + '")',
        f"        module.{cn} = {cn}",
        f'        assert PluginLoader().register_module(module) == ["{tid}"]',
        "",
        "    def test_metadata(self):",
        f"        assert isinstance({cn}.metadata, PluginMetadata)",
        f'        assert {cn}.metadata.type_id == "{tid}"',
        "",
        "    async def test_configure_fills_config(self, plugin):",
        "        await plugin.configure({})",
        "        assert isinstance(plugin.config, dict)",
        "",
        "    async def test_validate_config(self):",
        f"        assert await {cn}.validate_config({{}}) in (True, False)",
        "",
    ]

    return "\n".join(lines)


def create_plugin(args: argparse.Namespace) -> int:
    plugin_id = args.id
    plugin_type = args.type
    name = args.name or " ".join(p.title() for p in plugin_id.replace("-", "_").split("_"))
    description = args.description or f"A {plugin_type} plugin."
    author = args.author or ""
    single_instance = args.single or (plugin_type in DEFAULT_SINGLE)
    instance_label = args.label or (
        None if single_instance else DEFAULT_INSTANCE_LABELS.get(plugin_type, "Instance")
    )

    target = REPO_ROOT / plugin_id
    if target.exists():
        print(f"Error: directory '{plugin_id}' already exists.", file=sys.stderr)
        return 1

    target.mkdir()

    (target / "plugin.json").write_text(
        generate_plugin_json(plugin_id, name, plugin_type, description, author),
        encoding="utf-8",
    )

    (target / "plugin.py").write_text(
        generate_plugin_py(
            plugin_id, name, plugin_type, description, single_instance, instance_label
        ),
        encoding="utf-8",
    )

    tid = to_type_id(plugin_id)
    if not args.no_tests:
        (target / f"test_{tid}.py").write_text(
            generate_test_py(plugin_id, name, plugin_type),
            encoding="utf-8",
        )

    print(f"Created {plugin_id}/")
    print("  plugin.json")
    print("  plugin.py")
    if not args.no_tests:
        print(f"  test_{tid}.py")
    print()
    print("Next steps:")
    print(f"  1. Edit {plugin_id}/plugin.py — fill in instance_config_schema and business logic")
    print(f"  2. Run:  python scripts/validate_plugins.py {plugin_id}")
    print(f"  3. Run:  cd calvin/backend && uv run pytest ../../calvin-plugins/{plugin_id}")

    try:
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "rebuild-manifest.py")],
            check=True,
            capture_output=True,
        )
        print("  (plugins.json updated automatically)")
    except subprocess.CalledProcessError:
        print("  Note: run `python scripts/rebuild-manifest.py` to update plugins.json")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scaffold a new Calvin plugin",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("type", choices=["service", "image", "calendar", "backend"])
    parser.add_argument("id", metavar="id", help="Plugin ID (e.g. my-weather)")
    parser.add_argument("--name", help="Human-readable name")
    parser.add_argument("--description", help="Short description")
    parser.add_argument("--single", action="store_true", help="Single-instance plugin")
    parser.add_argument("--label", help="Instance label in UI (e.g. Location, Device)")
    parser.add_argument("--author", help="Author name")
    parser.add_argument("--no-tests", action="store_true", help="Skip test file")
    args = parser.parse_args()
    return create_plugin(args)


if __name__ == "__main__":
    sys.exit(main())
