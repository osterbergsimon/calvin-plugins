"""Validate Calvin plugin metadata without importing plugin modules."""

from __future__ import annotations

import ast
import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Mirrors backend app.services.csp.validate_origin (this repo cannot import the backend).
_HOST_SOURCE_RE = re.compile(
    r"^(?:\*\.)?(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?::\d{1,5})?$"
)


def _is_valid_host_source(value: str) -> bool:
    raw = value.strip()
    if not raw:
        return False
    host = raw
    if "://" in raw:
        scheme, host = raw.split("://", 1)
        if scheme.lower() not in ("http", "https"):
            return False
    if "/" in host or any(c in host for c in " \t?#"):
        return False
    return bool(_HOST_SOURCE_RE.match(host.lower()))

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
SUPPORTED_API_VERSION = 1
# Keys from the retired pre-1.0 display contract; their presence fails validation.
LEGACY_DISPLAY_KEYS = frozenset({"type", "api_endpoint", "render_template", "component", "data_schema"})
# Family protocol base class -> plugin type
FAMILY_BASES = {
    "CalendarPlugin": "calendar",
    "ImagePlugin": "image",
    "ServicePlugin": "service",
    "BackendPlugin": "backend",
    "SelfHostedGalleryImagePlugin": "image",
}


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
    display_schema: ast.Dict | None = None
    statusbar_schema: ast.Dict | None = None
    browser_origins: ast.List | None = None
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
    """Find `metadata = PluginMetadata(...)` class attributes (contract 1.0)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.records: list[MetadataRecord] = []

    @staticmethod
    def _is_plugin_metadata_call(node: ast.AST | None) -> bool:
        if not isinstance(node, ast.Call):
            return False
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        return name == "PluginMetadata"

    @staticmethod
    def _family_from_bases(class_node: ast.ClassDef) -> str | None:
        for base in class_node.bases:
            base_name = getattr(base, "id", None) or getattr(base, "attr", None)
            if base_name in FAMILY_BASES:
                return FAMILY_BASES[base_name]
        return None

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for statement in node.body:
            if not isinstance(statement, ast.Assign):
                continue
            targets = [getattr(t, "id", None) for t in statement.targets]
            if "metadata" not in targets or not self._is_plugin_metadata_call(statement.value):
                continue
            call = statement.value
            self.records.append(
                MetadataRecord(
                    path=self.path,
                    type_id=literal_string(keyword(call, "type_id")),
                    plugin_type=self._family_from_bases(node),
                    supports_multiple_instances=literal_bool(
                        keyword(call, "supports_multiple_instances")
                    ),
                    instance_label=literal_string(keyword(call, "instance_label")),
                    common_config_schema=keyword(call, "common_config_schema")
                    if isinstance(keyword(call, "common_config_schema"), ast.Dict)
                    else None,
                    instance_config_schema=keyword(call, "instance_config_schema")
                    if isinstance(keyword(call, "instance_config_schema"), ast.Dict)
                    else None,
                    ui_actions=keyword(call, "ui_actions")
                    if isinstance(keyword(call, "ui_actions"), ast.List)
                    else None,
                    display_schema=keyword(call, "display_schema")
                    if isinstance(keyword(call, "display_schema"), ast.Dict)
                    else None,
                    statusbar_schema=keyword(call, "statusbar_schema")
                    if isinstance(keyword(call, "statusbar_schema"), ast.Dict)
                    else None,
                    browser_origins=keyword(call, "browser_origins")
                    if isinstance(keyword(call, "browser_origins"), ast.List)
                    else None,
                )
            )
            bo_node = keyword(call, "browser_origins")
            if bo_node is not None and not isinstance(bo_node, ast.List):
                self.records[-1].errors.append(
                    "browser_origins must be a list literal of host-source strings"
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


def validate_display(record: MetadataRecord, schema_name: str, schema: ast.Dict | None) -> None:
    if schema is None:
        return
    keys = {literal_string(k) for k in schema.keys}
    legacy = sorted(k for k in keys if k in LEGACY_DISPLAY_KEYS)
    if legacy:
        record.errors.append(f"{schema_name} uses retired pre-1.0 keys: {', '.join(legacy)}")
    if "kind" not in keys:
        record.errors.append(f"{schema_name} must declare a kind")


def validate_browser_origins(record: MetadataRecord) -> None:
    if record.browser_origins is None:
        return
    for elt in record.browser_origins.elts:
        literal = literal_string(elt)
        if literal is None:
            record.errors.append("browser_origins entries must be string literals")
            continue
        if not _is_valid_host_source(literal):
            record.errors.append(
                f"browser_origins entry {literal!r} is not a valid CSP host-source "
                "(no CIDR/paths; use a host, host:port, *.wildcard, or http(s):// URL)"
            )


def validate_record(record: MetadataRecord) -> None:
    if not record.type_id:
        record.errors.append("metadata is missing literal type_id")
    if record.supports_multiple_instances is not False and not record.instance_label:
        record.errors.append("multi-instance metadata must declare instance_label")

    validate_schema(record, "common_config_schema", record.common_config_schema)
    validate_schema(record, "instance_config_schema", record.instance_config_schema)
    validate_display(record, "display_schema", record.display_schema)
    validate_display(record, "statusbar_schema", record.statusbar_schema)
    validate_actions(record)
    validate_browser_origins(record)


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

    api_version = manifest.get("api_version")
    if api_version is None:
        errors.append(
            f"{display_path(manifest_path)}: missing required field 'api_version' "
            f"(current: {SUPPORTED_API_VERSION})"
        )
    elif isinstance(api_version, bool) or api_version != SUPPORTED_API_VERSION:
        errors.append(
            f"{display_path(manifest_path)}: unsupported api_version '{api_version}' "
            f"(expected {SUPPORTED_API_VERSION})"
        )

    for retired in ("format_version", "protocol_version"):
        if retired in manifest:
            errors.append(
                f"{display_path(manifest_path)}: '{retired}' was retired in contract 1.0 "
                "— declare api_version instead"
            )
    deps = manifest.get("dependencies")
    if deps is not None:
        if not isinstance(deps, dict):
            errors.append(f"{display_path(manifest_path)}: dependencies must be an object")
        else:
            for retired_dep in ("python", "calvin"):
                if retired_dep in deps:
                    errors.append(
                        f"{display_path(manifest_path)}: dependencies.{retired_dep} was retired "
                        "in contract 1.0"
                    )
            packages = deps.get("packages")
            if packages is not None and (
                not isinstance(packages, list)
                or not all(isinstance(pkg, str) and pkg.strip() for pkg in packages)
            ):
                errors.append(
                    f"{display_path(manifest_path)}: dependencies.packages must be a list "
                    "of pip requirement strings"
                )
    if "python_dependencies" in manifest:
        errors.append(
            f"{display_path(manifest_path)}: 'python_dependencies' was retired in contract 1.0 "
            "— use dependencies.packages"
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
