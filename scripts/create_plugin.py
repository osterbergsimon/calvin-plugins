#!/usr/bin/env python3
"""
Scaffold a new Calvin plugin.

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


def to_class_name(plugin_id: str) -> str:
    """Convert my-plugin or my_plugin to MyPlugin."""
    return "".join(part.title() for part in plugin_id.replace("-", "_").split("_"))


def to_type_id(plugin_id: str) -> str:
    """Normalise to snake_case type_id."""
    return plugin_id.replace("-", "_")


def generate_plugin_json(plugin_id, name, plugin_type, description, author):
    manifest = {
        "format_version": "1.0.0",
        "protocol_version": 1,
        "id": to_type_id(plugin_id),
        "name": name,
        "version": "1.0.0",
        "type": plugin_type,
        "description": description,
        "author": author,
        "license": "MIT",
    }
    return json.dumps(manifest, indent=2) + "\n"


def _protocol_methods(plugin_type: str) -> list[str]:
    """Return lines (without trailing newline) for the type-specific protocol methods."""
    if plugin_type == "service":
        return [
            "    async def get_content(self) -> dict[str, Any]:",
            "        return {",
            '            "type": "api",',
            '            "url": f"/api/plugins/{self.plugin_id}/data",',
            "        }",
            "",
            "    async def validate_config(self, config: dict[str, Any]) -> bool:",
            "        return True",
        ]
    if plugin_type == "image":
        return [
            "    async def get_images(self) -> list[dict[str, Any]]:",
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
            "        self, start_date: str | None = None, end_date: str | None = None",
            "    ) -> list[dict[str, Any]]:",
            "        return []",
            "",
            "    async def validate_config(self, config: dict[str, Any]) -> bool:",
            "        return True",
        ]
    # backend
    return [
        "    async def validate_config(self, config: dict[str, Any]) -> bool:",
        "        return True",
    ]


def generate_plugin_py(plugin_id, name, plugin_type, description, single_instance, instance_label):
    cn = to_class_name(plugin_id) + PLUGIN_CLASS_MAP[plugin_type].replace("Plugin", "")
    base = PLUGIN_CLASS_MAP[plugin_type]
    tid = to_type_id(plugin_id)
    multi = "False" if single_instance else "True"

    if single_instance:
        im_args = f'type_id="{tid}", single_instance=True, instance_id="{tid}-instance"'
    else:
        im_args = f'type_id="{tid}", single_instance=False'

    if plugin_type == "service":
        lines = [
            f'"""{name} plugin."""',
            "",
            "from typing import Any",
            "",
            "from app.plugins.hooks import hookimpl",
            "from app.plugins.protocols import ServicePlugin",
            "from app.plugins.sdk.service import (",
            "    ServiceConfigField,",
            "    build_service_manager_config,",
            "    build_service_plugin_metadata,",
            "    create_service_plugin_instance,",
            ")",
            "from app.plugins.utils.instance_manager import handle_plugin_config_update_generic",
            "",
            "",
            "SERVICE_FIELDS = (",
            "    # TODO: add your config fields here",
            '    # ServiceConfigField("api_key", default="", converter=str),',
            ")",
            "",
            "",
            f"class {cn}(ServicePlugin):",
            f'    """{description}"""',
            "",
            "    @classmethod",
            "    def get_plugin_metadata(cls) -> dict[str, Any]:",
            "        return build_service_plugin_metadata(",
            f'            type_id="{tid}",',
            f'            name="{name}",',
            f'            description="{description}",',
            "            plugin_class=cls,",
            f"            supports_multiple_instances={multi},",
        ]

        if instance_label:
            lines.append(f'            instance_label="{instance_label}",')

        lines += [
            "            common_config_schema={},",
            "            instance_config_schema={",
            "                # TODO: add your config fields here",
            '                # "my_field": {',
            '                #     "type": "string",',
            '                #     "description": "A required field",',
            '                #     "default": "",',
            '                #     "ui": {"component": "input", "validation": {"required": True}},',
            "                # },",
            "            },",
            "        )",
            "",
            "    def __init__(self, plugin_id: str, name: str, enabled: bool = True):",
            "        super().__init__(plugin_id, name, enabled)",
            "        # TODO: assign config-backed instance variables",
            "",
            "    async def initialize(self) -> None:",
            "        pass",
            "",
            "    async def cleanup(self) -> None:",
            "        pass",
            "",
            "    async def get_content(self) -> dict[str, Any]:",
            "        return {",
            '            "type": "api",',
            '            "url": f"/api/plugins/{self.plugin_id}/data",',
            "        }",
            "",
            "    async def validate_config(self, config: dict[str, Any]) -> bool:",
            "        return True",
            "",
            "    async def configure(self, config: dict[str, Any]) -> None:",
            "        await super().configure(config)",
            "        # TODO: update instance variables from config",
            "",
            "",
            "@hookimpl",
            "def register_plugin_types() -> list[dict[str, Any]]:",
            f"    return [{cn}.get_plugin_metadata()]",
            "",
            "",
            "@hookimpl",
            "def create_plugin_instance(",
            "    plugin_id: str, type_id: str, name: str, config: dict[str, Any]",
            f") -> {cn} | None:",
            "    return create_service_plugin_instance(",
            f"        {cn},",
            f'        expected_type_id="{tid}",',
            "        plugin_id=plugin_id,",
            "        type_id=type_id,",
            "        name=name,",
            "        config=config,",
            "        fields=SERVICE_FIELDS,",
            "    )",
            "",
            "",
            "@hookimpl",
            "async def handle_plugin_config_update(",
            "    type_id: str, config: dict[str, Any], enabled: bool | None, db_type: Any, session: Any",
            ") -> dict[str, Any] | None:",
            f'    if type_id != "{tid}":',
            "        return None",
            "    return await handle_plugin_config_update_generic(",
            "        type_id,",
            "        config,",
            "        enabled,",
            "        db_type,",
            "        session,",
            "        build_service_manager_config(",
            f'            type_id="{tid}",',
            "            fields=SERVICE_FIELDS,",
            f"            single_instance={str(single_instance)},",
        ]

        if single_instance:
            lines.append(f'            instance_id="{tid}-instance",')

        lines += [
            f'            default_instance_name="{name}",',
            "        ),",
            "    )",
            "",
        ]
        return "\n".join(lines)

    lines = [
        f'"""{name} plugin."""',
        "",
        "from typing import Any",
        "",
        "from app.plugins.base import PluginType",
        "from app.plugins.hooks import hookimpl",
        f"from app.plugins.protocols import {base}",
        "from app.plugins.utils.instance_manager import InstanceManagerConfig, handle_plugin_config_update_generic",
        "",
        "",
        f"class {cn}({base}):",
        f'    """{description}"""',
        "",
        "    @classmethod",
        "    def get_plugin_metadata(cls) -> dict[str, Any]:",
        "        return {",
        f'            "type_id": "{tid}",',
        f'            "plugin_type": PluginType.{plugin_type.upper()},',
        f'            "name": "{name}",',
        f'            "description": "{description}",',
        '            "version": "1.0.0",',
        f'            "supports_multiple_instances": {multi},',
    ]

    if instance_label:
        lines.append(f'            "instance_label": "{instance_label}",')

    lines += [
        '            "common_config_schema": {},',
        '            "instance_config_schema": {',
        "                # TODO: add your config fields here",
        '                # "my_field": {',
        '                #     "type": "string",',
        '                #     "description": "A required field",',
        '                #     "default": "",',
        '                #     "ui": {"component": "input", "validation": {"required": True}},',
        "                # },",
        "            },",
        '            "plugin_class": cls,',
        "        }",
        "",
        "    def __init__(self, plugin_id: str, name: str, enabled: bool = True):",
        "        super().__init__(plugin_id, name, enabled)",
        "        # TODO: add instance variables for your config fields",
        "",
        "    async def initialize(self) -> None:",
        "        pass",
        "",
        "    async def cleanup(self) -> None:",
        "        pass",
        "",
    ]

    lines += _protocol_methods(plugin_type)

    lines += [
        "",
        "    async def configure(self, config: dict[str, Any]) -> None:",
        "        await super().configure(config)",
        "        # TODO: extract config fields with extract_config_value()",
        "",
        "",
        "@hookimpl",
        "def register_plugin_types() -> list[dict[str, Any]]:",
        f"    return [{cn}.get_plugin_metadata()]",
        "",
        "",
        "@hookimpl",
        "def create_plugin_instance(",
        "    plugin_id: str, type_id: str, name: str, config: dict[str, Any]",
        f") -> {cn} | None:",
        f'    if type_id != "{tid}":',
        "        return None",
        f'    return {cn}(plugin_id=plugin_id, name=name, enabled=config.get("enabled", False))',
        "",
        "",
        "@hookimpl",
        "async def handle_plugin_config_update(",
        "    type_id: str, config: dict[str, Any], enabled: bool | None, db_type: Any, session: Any",
        ") -> dict[str, Any] | None:",
        f'    if type_id != "{tid}":',
        "        return None",
        "    return await handle_plugin_config_update_generic(",
        "        type_id, config, enabled, db_type, session,",
        f"        InstanceManagerConfig({im_args}),",
        "    )",
        "",
    ]

    return "\n".join(lines)


def generate_test_py(plugin_id, name, plugin_type):
    cn = to_class_name(plugin_id) + PLUGIN_CLASS_MAP[plugin_type].replace("Plugin", "")
    tid = to_type_id(plugin_id)

    lines = [
        f'"""Tests for {name}.',
        "",
        "Run from the backend directory:",
        f"    cd backend && pytest ../{plugin_id}/test_{tid}.py -v",
        '"""',
        "",
        "import importlib.util",
        "from pathlib import Path",
        "",
        "import pytest",
        "",
        f'_spec = importlib.util.spec_from_file_location("{tid}", Path(__file__).parent / "plugin.py")',
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
        "    def test_metadata(self):",
        f"        meta = {cn}.get_plugin_metadata()",
        f'        assert meta["type_id"] == "{tid}"',
        f'        assert meta["name"] == "{name}"',
        "",
        "    def test_init(self, plugin):",
        '        assert plugin.plugin_id == "test"',
        "        assert plugin.enabled is True",
        "",
        "    @pytest.mark.asyncio",
        "    async def test_validate_config(self, plugin):",
        "        assert await plugin.validate_config({}) is True",
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
    instance_label = args.label

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
    print(f"  plugin.json")
    print(f"  plugin.py")
    if not args.no_tests:
        print(f"  test_{tid}.py")
    print()
    print("Next steps:")
    print(f"  1. Edit {plugin_id}/plugin.py — fill in instance_config_schema and business logic")
    print(f"  2. Run:  cd backend && pytest ../{plugin_id}/test_{tid}.py -v")

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
