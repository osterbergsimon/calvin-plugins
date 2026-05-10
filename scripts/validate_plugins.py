"""Validate Calvin plugin metadata without importing plugin modules."""

from __future__ import annotations

import ast
import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

APP_MANAGED_CONFIG_FIELD_KEYS = frozenset(
    {
        "common_config_schema",
        "config",
        "created_at",
        "display_order",
        "display_schema",
        "enabled",
        "id",
        "instance_config_schema",
        "instance_label",
        "name",
        "plugin_id",
        "plugin_type",
        "running",
        "statusbar_schema",
        "supports_multiple_instances",
        "type",
        "type_id",
        "ui_actions",
        "ui_sections",
        "updated_at",
    }
)

VALID_ACTION_SCOPES = frozenset({"global", "instance"})
VALID_PLUGIN_TYPES = frozenset({"calendar", "image", "service", "backend", "theme"})
REQUIRED_PLUGIN_MANIFEST_FIELDS = ("id", "name", "version", "type")
SUPPORTED_FORMAT_VERSION = "1.0.0"
SUPPORTED_PROTOCOL_VERSION = 1


@dataclass
class MetadataRecord:
    path: Path
    type_id: str | None = None
    plugin_type: str | None = None
    supports_multiple_instances: bool | None = None
    instance_label: str | None = None
    common_config_schema: ast.Dict | None = None
    instance_config_schema: ast.Dict | None = None
    ui_actions: ast.List | None = None
    errors: list[str] = field(default_factory=list)


def literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def literal_bool(node: ast.AST | None) -> bool | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return node.value
    return None


def literal_plugin_type(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Attribute):
        return node.attr.lower()
    return None


def keyword(call: ast.Call, name: str) -> ast.AST | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def load_json(path: Path) -> tuple[dict | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "file does not exist"
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    except OSError as exc:
        return None, f"could not read file: {exc}"

    if not isinstance(data, dict):
        return None, "must contain a JSON object"
    return data, None


class MetadataVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.records: list[MetadataRecord] = []

    def visit_Call(self, node: ast.Call) -> None:
        func_name = getattr(node.func, "id", None)
        if func_name and func_name.startswith("build_") and func_name.endswith("_plugin_metadata"):
            inferred_plugin_type = func_name.removeprefix("build_").removesuffix(
                "_plugin_metadata"
            )
            self.records.append(
                MetadataRecord(
                    path=self.path,
                    type_id=literal_string(keyword(node, "type_id")),
                    plugin_type=inferred_plugin_type,
                    supports_multiple_instances=literal_bool(
                        keyword(node, "supports_multiple_instances")
                    ),
                    instance_label=literal_string(keyword(node, "instance_label")),
                    common_config_schema=keyword(node, "common_config_schema")
                    if isinstance(keyword(node, "common_config_schema"), ast.Dict)
                    else None,
                    instance_config_schema=keyword(node, "instance_config_schema")
                    if isinstance(keyword(node, "instance_config_schema"), ast.Dict)
                    else None,
                    ui_actions=keyword(node, "ui_actions")
                    if isinstance(keyword(node, "ui_actions"), ast.List)
                    else None,
                )
            )
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        keys = {literal_string(k): v for k, v in zip(node.keys, node.values)}
        if "type_id" in keys and "plugin_type" in keys:
            self.records.append(
                MetadataRecord(
                    path=self.path,
                    type_id=literal_string(keys.get("type_id")),
                    plugin_type=literal_plugin_type(keys.get("plugin_type")),
                    supports_multiple_instances=literal_bool(
                        keys.get("supports_multiple_instances")
                    ),
                    instance_label=literal_string(keys.get("instance_label")),
                    common_config_schema=keys.get("common_config_schema")
                    if isinstance(keys.get("common_config_schema"), ast.Dict)
                    else None,
                    instance_config_schema=keys.get("instance_config_schema")
                    if isinstance(keys.get("instance_config_schema"), ast.Dict)
                    else None,
                    ui_actions=keys.get("ui_actions")
                    if isinstance(keys.get("ui_actions"), ast.List)
                    else None,
                )
            )
        self.generic_visit(node)


def validate_schema(record: MetadataRecord, schema_name: str, schema: ast.Dict | None) -> None:
    if schema is None:
        return

    for key_node, value_node in zip(schema.keys, schema.values):
        key = literal_string(key_node)
        if key is None:
            record.errors.append(f"{schema_name} contains a non-literal field key")
            continue
        if key in APP_MANAGED_CONFIG_FIELD_KEYS:
            record.errors.append(f"{schema_name}.{key} is app-managed")
        if not isinstance(value_node, ast.Dict):
            record.errors.append(f"{schema_name}.{key} must be a schema object")


def validate_actions(record: MetadataRecord) -> None:
    if record.ui_actions is None:
        return

    for action_node in record.ui_actions.elts:
        if not isinstance(action_node, ast.Dict):
            record.errors.append("ui_actions entries must be objects")
            continue

        action = {literal_string(k): v for k, v in zip(action_node.keys, action_node.values)}
        action_id = literal_string(action.get("id")) or "<unknown>"
        scope = literal_string(action.get("scope"))
        if scope not in VALID_ACTION_SCOPES:
            record.errors.append(
                f"ui_actions.{action_id} must declare scope 'global' or 'instance'"
            )


def validate_record(record: MetadataRecord) -> None:
    if not record.type_id:
        record.errors.append("metadata is missing literal type_id")
    if record.supports_multiple_instances is not False and not record.instance_label:
        record.errors.append("multi-instance metadata must declare instance_label")

    validate_schema(record, "common_config_schema", record.common_config_schema)
    validate_schema(record, "instance_config_schema", record.instance_config_schema)
    validate_actions(record)


def plugin_paths() -> list[Path]:
    manifest = json.loads((REPO_ROOT / "plugins.json").read_text(encoding="utf-8"))
    return [
        REPO_ROOT / plugin["path"] / "plugin.py"
        for plugin in manifest.get("plugins", [])
        if (REPO_ROOT / plugin["path"] / "plugin.py").exists()
    ]


def normalize_plugin_path(path: Path) -> Path:
    if path.is_dir():
        return path / "plugin.py"
    return path


def resolved_plugin_paths(paths: list[Path] | None = None) -> list[Path]:
    return [normalize_plugin_path(path) for path in paths] if paths else plugin_paths()


def validate_plugin_manifest(plugin_py: Path) -> tuple[list[str], dict | None]:
    errors: list[str] = []
    plugin_dir = plugin_py.parent
    manifest_path = plugin_dir / "plugin.json"

    if not plugin_py.exists():
        errors.append(f"{display_path(plugin_py)}: plugin.py not found")
        return errors, None

    manifest, manifest_error = load_json(manifest_path)
    if manifest_error:
        errors.append(f"{display_path(manifest_path)}: {manifest_error}")
        return errors, None

    assert manifest is not None
    for field_name in REQUIRED_PLUGIN_MANIFEST_FIELDS:
        if not manifest.get(field_name):
            errors.append(f"{display_path(manifest_path)}: missing required field '{field_name}'")

    plugin_type = manifest.get("type")
    if plugin_type and plugin_type not in VALID_PLUGIN_TYPES:
        errors.append(
            f"{display_path(manifest_path)}: invalid type '{plugin_type}' "
            f"(expected one of {', '.join(sorted(VALID_PLUGIN_TYPES))})"
        )

    format_version = manifest.get("format_version", SUPPORTED_FORMAT_VERSION)
    if format_version != SUPPORTED_FORMAT_VERSION:
        errors.append(
            f"{display_path(manifest_path)}: unsupported format_version '{format_version}' "
            f"(expected {SUPPORTED_FORMAT_VERSION})"
        )

    protocol_version = manifest.get("protocol_version", SUPPORTED_PROTOCOL_VERSION)
    if protocol_version != SUPPORTED_PROTOCOL_VERSION:
        errors.append(
            f"{display_path(manifest_path)}: unsupported protocol_version '{protocol_version}' "
            f"(expected {SUPPORTED_PROTOCOL_VERSION})"
        )

    return errors, manifest


def validate_manifest_matches_metadata(
    plugin_py: Path, manifest: dict | None, records: list[MetadataRecord]
) -> list[str]:
    if manifest is None:
        return []

    errors: list[str] = []
    manifest_id = manifest.get("id")
    manifest_type = manifest.get("type")
    for record in records:
        if manifest_id and record.type_id and manifest_id != record.type_id:
            errors.append(
                f"{display_path(plugin_py)}: metadata type_id '{record.type_id}' "
                f"does not match plugin.json id '{manifest_id}'"
            )
        if manifest_type and record.plugin_type and manifest_type != record.plugin_type:
            errors.append(
                f"{display_path(plugin_py)}: metadata plugin_type '{record.plugin_type}' "
                f"does not match plugin.json type '{manifest_type}'"
            )
    return errors


def validate_plugins(paths: list[Path] | None = None) -> list[str]:
    errors: list[str] = []
    for path in resolved_plugin_paths(paths):
        manifest_errors, manifest = validate_plugin_manifest(path)
        errors.extend(manifest_errors)
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = MetadataVisitor(path)
        visitor.visit(tree)
        if not visitor.records:
            errors.append(f"{display_path(path)}: no plugin metadata found")
            continue
        errors.extend(validate_manifest_matches_metadata(path, manifest, visitor.records))
        for record in visitor.records:
            validate_record(record)
            for error in record.errors:
                errors.append(f"{display_path(path)}: {error}")
    return errors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate Calvin plugin packages and metadata without importing plugins."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help=(
            "Plugin directories or plugin.py files to validate. "
            "Defaults to all plugins listed in plugins.json."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    errors = validate_plugins(args.paths or None)
    if errors:
        for error in errors:
            print(error)
        return 1
    count = len(resolved_plugin_paths(args.paths or None))
    print(f"Plugin validation passed ({count} plugin{'s' if count != 1 else ''})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
