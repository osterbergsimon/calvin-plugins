"""Validate Calvin plugin metadata without importing plugin modules."""

from __future__ import annotations

import ast
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


@dataclass
class MetadataRecord:
    path: Path
    type_id: str | None = None
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


class MetadataVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.records: list[MetadataRecord] = []

    def visit_Call(self, node: ast.Call) -> None:
        func_name = getattr(node.func, "id", None)
        if func_name and func_name.startswith("build_") and func_name.endswith("_plugin_metadata"):
            self.records.append(
                MetadataRecord(
                    path=self.path,
                    type_id=literal_string(keyword(node, "type_id")),
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


def validate_plugins(paths: list[Path] | None = None) -> list[str]:
    errors: list[str] = []
    for path in paths or plugin_paths():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = MetadataVisitor(path)
        visitor.visit(tree)
        if not visitor.records:
            errors.append(f"{display_path(path)}: no plugin metadata found")
            continue
        for record in visitor.records:
            validate_record(record)
            for error in record.errors:
                errors.append(f"{display_path(path)}: {error}")
    return errors


def main() -> int:
    errors = validate_plugins()
    if errors:
        for error in errors:
            print(error)
        return 1
    print("Plugin metadata validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
