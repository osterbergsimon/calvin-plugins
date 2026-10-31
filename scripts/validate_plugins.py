"""Validate Calvin plugin metadata without importing plugin modules."""

from __future__ import annotations

import ast
import argparse
import colorsys
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

# Copy rules (docs/design/2026-10-31-plugin-copy.md §5).
PLUGIN_NAME_MAX = 28
PLUGIN_DESCRIPTION_MAX = 90
FIELD_DESCRIPTION_MAX = 120
ICON_RE = re.compile(r"^mdi:[a-z0-9-]+$")
# Mirrors the host's curated map in frontend/src/utils/pluginIcon.js.
SUPPORTED_PLUGIN_ICONS = frozenset(
    {
        "mdi:book-open-page-variant",
        "mdi:bus-clock",
        "mdi:calendar",
        "mdi:camera-outline",
        "mdi:cast",
        "mdi:chart-line",
        "mdi:clock-outline",
        "mdi:email-outline",
        "mdi:filmstrip",
        "mdi:flask-outline",
        "mdi:folder-image",
        "mdi:gauge",
        "mdi:home",
        "mdi:image",
        "mdi:image-auto-adjust",
        "mdi:image-multiple",
        "mdi:lightbulb",
        "mdi:map-marker",
        "mdi:music",
        "mdi:newspaper",
        "mdi:puzzle-outline",
        "mdi:rss",
        "mdi:shuffle-variant",
        "mdi:silverware-fork-knife",
        "mdi:speaker",
        "mdi:telescope",
        "mdi:television",
        "mdi:video",
        "mdi:weather-partly-cloudy",
        "mdi:web",
    }
)
# Proper nouns and acronyms allowed to stay capitalised inside a field label.
SENTENCE_CASE_ALLOWLIST = frozenset(
    {
        "API",
        "Chromecast",
        "Gmail",
        "Google",
        "ID",
        "Immich",
        "Lychee",
        "Mealie",
        "NASA",
        "Outlook",
        "SL",
        "TV",
        "Unsplash",
        "Yr",
    }
)
# Placeholder example hosts are examples, not links (the copy rule bans URLs).
_PLACEHOLDER_URL_RE = re.compile(
    r"https?://(?:[a-z0-9-]+\.)*(?:example\.com|local)(?::\d{1,5})?", re.IGNORECASE
)

# Theme contract 2 (docs/design/2026-10-31-themes-audit.md §4).
THEME_API_VERSION = 2
THEME_BASE_KEYS = (
    "bg-0",
    "bg-1",
    "bg-2",
    "ink",
    "ink-2",
    "ink-3",
    "line",
    "line-soft",
    "focus",
    "ok",
    "warn",
    "err",
    "shadow",
    "shadow-hover",
)
THEME_TONE_KEYS = ("focus", "ok", "warn", "err")
THEME_PAIR_KEYS = tuple(
    f"{tone}{suffix}" for tone in THEME_TONE_KEYS for suffix in ("-ink", "-text")
)
THEME_EVENT_KEYS = tuple(f"event-{index}" for index in range(1, 9))
THEME_ALLOWED_KEYS = frozenset(THEME_BASE_KEYS + THEME_PAIR_KEYS + THEME_EVENT_KEYS)
THEME_HUE_RULES = {
    ("focus", "ok"): 25,
    ("focus", "err"): 25,
    ("warn", "err"): 25,
    ("focus", "warn"): 12,
}
THEME_AA_RATIO = 4.5
_THEME_HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\Z")
_THEME_FUNC_RE = re.compile(
    r"(?:rgb|rgba|hsl|hsla)\(\s*[0-9.%\s,/+-]+\s*\)\Z", re.IGNORECASE
)
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
    name: str | None = None
    description: str | None = None
    icon: str | None = None
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


def dict_value(node: ast.Dict, key: str) -> ast.AST | None:
    for key_node, value_node in zip(node.keys, node.values):
        if literal_string(key_node) == key:
            return value_node
    return None


def is_sentence_case(label: str) -> bool:
    """First letter upper, then lower-case words except known proper nouns."""
    text = label.strip()
    if not text or not text[0].isupper():
        return False
    for word in text.split()[1:]:
        token = word.strip(".,;:!?()[]{}…\"'")
        if not token:
            continue
        if token[0].isupper() and token not in SENTENCE_CASE_ALLOWLIST:
            return False
    return True


def has_disallowed_http(text: str) -> bool:
    """True when text contains a URL that is not a placeholder example."""
    return "http" in _PLACEHOLDER_URL_RE.sub("", text).lower()


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
                    name=literal_string(keyword(call, "name")),
                    description=literal_string(keyword(call, "description")),
                    icon=literal_string(keyword(call, "icon")),
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
            continue
        validate_field(record, schema_name, key, value_node)


def validate_field(
    record: MetadataRecord, schema_name: str, key: str, field_node: ast.Dict
) -> None:
    where = f"{schema_name}.{key}"

    label_node = dict_value(field_node, "label")
    label = literal_string(label_node)
    if label is None or not label.strip():
        record.errors.append(f"{where} must declare a non-empty label")
    elif not is_sentence_case(label):
        record.errors.append(f"{where} label {label!r} is not in sentence case")

    description_node = dict_value(field_node, "description")
    if description_node is not None:
        description = literal_string(description_node)
        if description is None:
            record.errors.append(f"{where}.description must be a string literal")
        else:
            text = description.strip()
            if len(text) > FIELD_DESCRIPTION_MAX:
                record.errors.append(
                    f"{where}.description is longer than {FIELD_DESCRIPTION_MAX} characters"
                )
            if not text.endswith("."):
                record.errors.append(f"{where}.description must end with a full stop")
            if has_disallowed_http(text):
                record.errors.append(f"{where}.description must not contain a URL")

    for flag in ("hidden", "required"):
        flag_node = dict_value(field_node, flag)
        if flag_node is not None and literal_bool(flag_node) is None:
            record.errors.append(f"{where}.{flag} must be a boolean")


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
    if not record.name:
        record.errors.append("metadata is missing literal name")
    elif len(record.name) > PLUGIN_NAME_MAX:
        record.errors.append(
            f"name {record.name!r} is longer than {PLUGIN_NAME_MAX} characters"
        )
    if not record.description:
        record.errors.append("metadata is missing literal description")
    else:
        description = record.description.strip()
        if len(description) > PLUGIN_DESCRIPTION_MAX:
            record.errors.append(
                f"description is longer than {PLUGIN_DESCRIPTION_MAX} characters"
            )
        if not description.endswith("."):
            record.errors.append("description must end with a full stop")
        if has_disallowed_http(description):
            record.errors.append("description must not contain a URL")
    if not record.icon:
        record.errors.append("metadata is missing icon")
    elif not ICON_RE.match(record.icon):
        record.errors.append(f"icon {record.icon!r} must look like mdi:<name>")
    elif record.icon not in SUPPORTED_PLUGIN_ICONS:
        record.errors.append(f"icon {record.icon!r} is not in the host's curated list")
    if record.instance_label:
        first = record.instance_label.strip().split()[0].strip(".,;:!?()[]{}…\"'")
        if (
            first
            and first[0].isupper()
            and first not in SENTENCE_CASE_ALLOWLIST
        ):
            record.errors.append(
                f"instance_label {record.instance_label!r} must be a lowercase noun phrase"
            )
    if record.supports_multiple_instances is not False and not record.instance_label:
        record.errors.append("multi-instance metadata must declare instance_label")

    validate_schema(record, "common_config_schema", record.common_config_schema)
    validate_schema(record, "instance_config_schema", record.instance_config_schema)
    validate_display(record, "display_schema", record.display_schema)
    validate_display(record, "statusbar_schema", record.statusbar_schema)
    validate_actions(record)
    validate_browser_origins(record)


def load_repository_manifest() -> dict | None:
    manifest, _ = load_json(REPO_ROOT / "plugins.json")
    return manifest


def published_plugin_ids(manifest: dict | None = None) -> list[str]:
    """Plugin ids shown in the catalog: entries with ``catalog: false`` are hidden."""
    data = manifest if manifest is not None else load_repository_manifest()
    if not isinstance(data, dict):
        return []
    return [
        entry["id"]
        for entry in data.get("plugins", [])
        if isinstance(entry, dict)
        and entry.get("id")
        and entry.get("catalog", True) is not False
    ]


def validate_repository_manifest() -> list[str]:
    errors: list[str] = []
    manifest, manifest_error = load_json(REPO_ROOT / "plugins.json")
    if manifest_error:
        return [f"plugins.json: {manifest_error}"]
    assert manifest is not None
    for index, entry in enumerate(manifest.get("plugins", [])):
        if not isinstance(entry, dict):
            errors.append(f"plugins.json: plugin entry {index} must be an object")
            continue
        if "catalog" in entry and not isinstance(entry["catalog"], bool):
            errors.append(f"plugins.json: catalog must be a boolean for {entry.get('id', index)}")
    for index, entry in enumerate(manifest.get("themes", [])):
        if not isinstance(entry, dict):
            errors.append(f"plugins.json: theme entry {index} must be an object")
    return errors


def theme_paths() -> list[Path]:
    manifest = load_repository_manifest()
    if not isinstance(manifest, dict):
        return []
    return [
        REPO_ROOT / theme["path"] / "theme.json"
        for theme in manifest.get("themes", [])
        if isinstance(theme, dict) and theme.get("path")
    ]


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


def is_theme_colour(value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    return bool(_THEME_HEX_RE.match(text) or _THEME_FUNC_RE.match(text))


def _parse_hex_colour(value: str) -> tuple[tuple[int, int, int], float]:
    raw = value.strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(channel * 2 for channel in raw)
    alpha = 1.0
    if len(raw) == 8:
        alpha = int(raw[6:8], 16) / 255
    return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)), alpha


def _colour_channel(value: str) -> int:
    text = value.strip()
    if text.endswith("%"):
        return round(float(text[:-1]) * 255 / 100)
    return round(float(text))


def _parse_func_colour(value: str) -> tuple[tuple[int, int, int], float]:
    name, _, rest = value.partition("(")
    args = rest.rstrip(")").replace("/", " ").replace(",", " ").split()
    if not args:
        raise ValueError("empty colour function")
    if name.lower().startswith("rgb"):
        rgb = tuple(max(0, min(255, _colour_channel(part))) for part in args[:3])
        alpha = (
            float(args[3].rstrip("%")) / (100 if args[3].endswith("%") else 1)
            if len(args) > 3
            else 1.0
        )
        return rgb, alpha  # type: ignore[return-value]
    hue_value = float(args[0].rstrip("deg"))
    saturation = float(args[1].rstrip("%")) / 100
    lightness = float(args[2].rstrip("%")) / 100
    alpha = (
        float(args[3].rstrip("%")) / (100 if args[3].endswith("%") else 1)
        if len(args) > 3
        else 1.0
    )
    red, green, blue = colorsys.hls_to_rgb(
        (hue_value % 360) / 360, lightness, saturation
    )
    return (round(red * 255), round(green * 255), round(blue * 255)), alpha


def parse_theme_colour(value: str) -> tuple[tuple[int, int, int], float]:
    text = value.strip()
    if text.startswith("#"):
        return _parse_hex_colour(text)
    return _parse_func_colour(text)


def _composite_colour(
    rgb: tuple[int, int, int], alpha: float, background: tuple[int, int, int]
) -> tuple[int, int, int]:
    if alpha >= 1:
        return rgb
    return tuple(
        round(channel * alpha + back * (1 - alpha))
        for channel, back in zip(rgb, background, strict=True)
    )  # type: ignore[return-value]


def _linear_channel(channel: int) -> float:
    value = channel / 255
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _luminance(rgb: tuple[int, int, int]) -> float:
    return (
        0.2126 * _linear_channel(rgb[0])
        + 0.7152 * _linear_channel(rgb[1])
        + 0.0722 * _linear_channel(rgb[2])
    )


def theme_contrast_ratio(
    first: tuple[int, int, int], second: tuple[int, int, int]
) -> float:
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _theme_rgb(
    value: str, background: tuple[int, int, int] = (255, 255, 255)
) -> tuple[int, int, int]:
    rgb, alpha = parse_theme_colour(value)
    return _composite_colour(rgb, alpha, background)


def theme_hue(value: str) -> float:
    red, green, blue = (channel / 255 for channel in _theme_rgb(value))
    return colorsys.rgb_to_hls(red, green, blue)[0] * 360


def theme_hue_distance(first: str, second: str) -> float:
    distance = abs(theme_hue(first) - theme_hue(second)) % 360
    return min(distance, 360 - distance)


def _validate_theme_mode(mode: str, raw: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(raw, dict):
        return [f"{mode} must be an object"]

    palette: dict[str, str] = {}
    for key, value in raw.items():
        if key not in THEME_ALLOWED_KEYS:
            errors.append(f"{mode}.{key} is not a colour token")
            continue
        if not is_theme_colour(value):
            errors.append(f"{mode}.{key} is not a valid colour")
            continue
        palette[key] = value.strip()

    missing = [key for key in THEME_BASE_KEYS if key not in palette]
    for key in missing:
        errors.append(f"missing {key} in {mode}")
    if missing:
        return errors

    background = _theme_rgb(palette["bg-1"])
    for key in ("ink", "ink-2", "ink-3"):
        if theme_contrast_ratio(_theme_rgb(palette[key]), background) < THEME_AA_RATIO:
            errors.append(f"{key} is below AA on bg-1 in {mode}")

    for tone in THEME_TONE_KEYS:
        tone_rgb = _theme_rgb(palette[tone], background)
        for suffix in ("-ink", "-text"):
            pair_key = f"{tone}{suffix}"
            if pair_key not in palette:
                continue  # the host derives a readable pair
            pair_rgb = _theme_rgb(palette[pair_key], background)
            target = tone_rgb if suffix == "-ink" else background
            if theme_contrast_ratio(pair_rgb, target) < THEME_AA_RATIO:
                where = tone if suffix == "-ink" else "bg-1"
                errors.append(f"{pair_key} is below AA on {where} in {mode}")

    for (first, second), minimum in THEME_HUE_RULES.items():
        distance = theme_hue_distance(palette[first], palette[second])
        if round(distance) < minimum:
            errors.append(
                f"{first} and {second} are {round(distance)}° apart in {mode} "
                f"(minimum {minimum}°)"
            )
    return errors


def validate_theme(theme_json: Path) -> list[str]:
    data, error = load_json(theme_json)
    if error:
        return [f"{display_path(theme_json)}: {error}"]
    assert data is not None

    errors: list[str] = []
    for field_name in ("id", "name", "version"):
        if not data.get(field_name):
            errors.append(f"missing required field '{field_name}'")
    if data.get("theme_api") != THEME_API_VERSION:
        errors.append(
            f"theme_api must be {THEME_API_VERSION} "
            f"(got {data.get('theme_api')!r})"
        )
    for mode in ("variables", "dark_mode"):
        errors.extend(_validate_theme_mode(mode, data.get(mode)))
    return [f"{display_path(theme_json)}: {message}" for message in errors]


def validate_themes() -> list[str]:
    errors: list[str] = []
    for path in theme_paths():
        if not path.exists():
            errors.append(f"{display_path(path)}: theme.json not found")
            continue
        errors.extend(validate_theme(path))
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
    if paths is None:
        errors.extend(validate_repository_manifest())
        errors.extend(validate_themes())
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
    summary = f"{count} plugin{'s' if count != 1 else ''}"
    if not args.paths:
        theme_count = len(theme_paths())
        summary += f" and {theme_count} theme{'s' if theme_count != 1 else ''}"
    print(f"Plugin validation passed ({summary})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
