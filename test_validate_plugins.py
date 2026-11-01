"""Tests for plugin metadata validation (contract 1.0)."""

import json
import os
import re
from pathlib import Path

import pytest

from conftest import load_script

_mod = load_script("validate_plugins")

VALID_PLUGIN_PY = """
from app.plugins.definitions import PluginMetadata
from app.plugins.protocols import ServicePlugin


class DemoServicePlugin(ServicePlugin):
    metadata = PluginMetadata(
        type_id="demo_plugin",
        name="Demo Plugin",
        description="Says demo.",
        icon="mdi:flask-outline",
        instance_label="source",
        instance_config_schema={},
        display_schema={"kind": "status", "item": {"label": "Demo", "value_path": "$.v"}},
    )

    async def fetch(self, start_date=None, end_date=None):
        return {"v": 1}
"""


def _manifest(**overrides):
    manifest = {
        "api_version": 1,
        "id": "demo_plugin",
        "name": "Demo Plugin",
        "version": "1.0.0",
        "type": "service",
    }
    manifest.update(overrides)
    return manifest


def write_valid_plugin(plugin_dir: Path, plugin_py_source: str = VALID_PLUGIN_PY) -> Path:
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(json.dumps(_manifest()), encoding="utf-8")
    plugin_py = plugin_dir / "plugin.py"
    plugin_py.write_text(plugin_py_source, encoding="utf-8")
    return plugin_py


def _set_manifest(plugin_dir: Path, **overrides):
    manifest_path = plugin_dir / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(overrides)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def test_owned_plugins_pass_metadata_validation():
    assert _mod.validate_plugins() == []


def test_validator_accepts_explicit_plugin_directory(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    write_valid_plugin(plugin_dir)

    assert _mod.validate_plugins([plugin_dir]) == []


def test_validator_accepts_explicit_plugin_py(tmp_path):
    plugin_py = write_valid_plugin(tmp_path / "demo-plugin")

    assert _mod.validate_plugins([plugin_py]) == []


def test_validator_rejects_reserved_schema_field(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    write_valid_plugin(
        plugin_dir,
        VALID_PLUGIN_PY.replace(
            "instance_config_schema={},",
            'instance_config_schema={"display_order": {"type": "integer"}},',
        ),
    )

    errors = _mod.validate_plugins([plugin_dir])

    assert any("instance_config_schema.display_order is app-managed" in error for error in errors)


def test_validator_rejects_hook_era_plugin(tmp_path):
    """A pre-1.0 plugin (builder call, no metadata class attr) fails discovery."""
    plugin_dir = tmp_path / "demo-plugin"
    write_valid_plugin(
        plugin_dir,
        """
def get_plugin_metadata():
    return {"type_id": "demo_plugin", "plugin_type": "service", "name": "Demo Plugin"}
""",
    )

    errors = _mod.validate_plugins([plugin_dir])

    assert any("no plugin metadata found" in error for error in errors)


def test_validator_rejects_legacy_display_schema(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    write_valid_plugin(
        plugin_dir,
        VALID_PLUGIN_PY.replace(
            'display_schema={"kind": "status", "item": {"label": "Demo", "value_path": "$.v"}},',
            'display_schema={"type": "api", "render_template": "weather"},',
        ),
    )

    errors = _mod.validate_plugins([plugin_dir])

    assert any("retired pre-1.0 keys" in error for error in errors)
    assert any("must declare a kind" in error for error in errors)


def test_validator_rejects_missing_api_version(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    write_valid_plugin(plugin_dir)
    manifest_path = plugin_dir / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["api_version"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    errors = _mod.validate_plugins([plugin_dir])

    assert any("missing required field 'api_version'" in error for error in errors)


def test_validator_rejects_retired_version_fields(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    write_valid_plugin(plugin_dir)
    _set_manifest(plugin_dir, format_version="1.0.0", protocol_version=1)

    errors = _mod.validate_plugins([plugin_dir])

    assert any("'format_version' was retired" in error for error in errors)
    assert any("'protocol_version' was retired" in error for error in errors)


def test_validator_rejects_retired_dependency_forms(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    write_valid_plugin(plugin_dir)
    _set_manifest(
        plugin_dir,
        python_dependencies=["psutil"],
        dependencies={"python": ">=3.10", "packages": ["ok>=1"]},
    )

    errors = _mod.validate_plugins([plugin_dir])

    assert any("'python_dependencies' was retired" in error for error in errors)
    assert any("dependencies.python was retired" in error for error in errors)


def test_validator_rejects_malformed_packages(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    write_valid_plugin(plugin_dir)
    _set_manifest(plugin_dir, dependencies={"packages": {"psutil": ">=5.9"}})

    errors = _mod.validate_plugins([plugin_dir])

    assert any("dependencies.packages must be a list" in error for error in errors)


def test_validator_rejects_missing_manifest_for_explicit_directory(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.py").write_text(VALID_PLUGIN_PY, encoding="utf-8")

    errors = _mod.validate_plugins([plugin_dir])

    assert any("plugin.json: file does not exist" in error for error in errors)


def test_validator_rejects_invalid_manifest_type(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    write_valid_plugin(plugin_dir)
    _set_manifest(plugin_dir, type="dashboard")

    errors = _mod.validate_plugins([plugin_dir])

    assert any("invalid type 'dashboard'" in error for error in errors)


def test_validator_rejects_manifest_metadata_id_mismatch(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    write_valid_plugin(plugin_dir)
    _set_manifest(plugin_dir, id="other_plugin")

    errors = _mod.validate_plugins([plugin_dir])

    assert any("metadata type_id 'demo_plugin' does not match" in error for error in errors)


def test_validator_rejects_manifest_metadata_type_mismatch(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    write_valid_plugin(plugin_dir)
    _set_manifest(plugin_dir, type="image")

    errors = _mod.validate_plugins([plugin_dir])

    assert any("metadata plugin_type 'service' does not match" in error for error in errors)


def test_validator_rejects_missing_plugin_py_for_explicit_directory(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(json.dumps(_manifest()), encoding="utf-8")

    errors = _mod.validate_plugins([plugin_dir])

    assert any("plugin.py not found" in error for error in errors)


def test_validator_rejects_unscoped_action(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    write_valid_plugin(
        plugin_dir,
        VALID_PLUGIN_PY.replace(
            "instance_config_schema={},",
            'instance_config_schema={},\n        ui_actions=[{"id": "test", "type": "test", "label": "Test"}],',
        ),
    )

    errors = _mod.validate_plugins([plugin_dir])

    assert any("ui_actions.test must declare scope" in error for error in errors)


def test_main_returns_success_and_prints_count(tmp_path, capsys):
    plugin_dir = tmp_path / "demo-plugin"
    write_valid_plugin(plugin_dir)

    result = _mod.main([str(plugin_dir)])

    captured = capsys.readouterr()
    assert result == 0
    assert "Plugin validation passed (1 plugin)" in captured.out


def test_main_returns_failure_for_invalid_plugin(tmp_path, capsys):
    plugin_dir = tmp_path / "demo-plugin"
    plugin_dir.mkdir()

    result = _mod.main([str(plugin_dir)])

    captured = capsys.readouterr()
    assert result == 1
    assert "plugin.py not found" in captured.out


_PY_WITH_BROWSER_ORIGINS = """
from app.plugins.definitions import PluginMetadata
from app.plugins.protocols import ServicePlugin


class DemoServicePlugin(ServicePlugin):
    metadata = PluginMetadata(
        type_id="demo_plugin",
        name="Demo Plugin",
        description="Says demo.",
        icon="mdi:flask-outline",
        instance_label="source",
        instance_config_schema={},
        display_schema={"kind": "status", "item": {"label": "Demo", "value_path": "$.v"}},
        browser_origins=[%s],
    )

    async def fetch(self, start_date=None, end_date=None):
        return {"v": 1}
"""


def test_validator_accepts_valid_browser_origins(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    src = _PY_WITH_BROWSER_ORIGINS % '"*.lab.example.com", "https://cast.example.com"'
    write_valid_plugin(plugin_dir, src)
    assert _mod.validate_plugins([plugin_dir]) == []


def test_validator_rejects_cidr_browser_origin(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    src = _PY_WITH_BROWSER_ORIGINS % '"10.0.0.0/24"'
    write_valid_plugin(plugin_dir, src)
    errors = _mod.validate_plugins([plugin_dir])
    assert any("browser_origins" in error for error in errors)


def test_validator_rejects_non_literal_browser_origin_element(tmp_path):
    # A list literal whose element is a name, not a string literal -> element path.
    plugin_dir = tmp_path / "demo-plugin"
    src = _PY_WITH_BROWSER_ORIGINS % "SOME_VAR"
    write_valid_plugin(plugin_dir, src)
    errors = _mod.validate_plugins([plugin_dir])
    assert any("must be string literals" in error for error in errors)


def test_validator_rejects_non_list_browser_origins(tmp_path):
    # browser_origins declared as a non-list value -> visitor's list-literal branch.
    plugin_dir = tmp_path / "demo-plugin"
    src = _PY_WITH_BROWSER_ORIGINS.replace("browser_origins=[%s],", 'browser_origins="notalist",')
    write_valid_plugin(plugin_dir, src)
    errors = _mod.validate_plugins([plugin_dir])
    assert any("must be a list literal" in error for error in errors)


def _plugin_with_schema(field_source: str) -> str:
    return VALID_PLUGIN_PY.replace(
        "instance_config_schema={},",
        f"instance_config_schema={{{field_source}}},",
    )


def _field(**overrides) -> str:
    field = {
        '"type": "string"',
        '"label": "Server address"',
        '"description": "Where the server lives."',
    }
    for key, value in overrides.items():
        if value is None:
            field = {entry for entry in field if not entry.startswith(f'"{key}"')}
        else:
            field = {entry for entry in field if not entry.startswith(f'"{key}"')}
            field.add(f'"{key}": {json.dumps(value)}')
    return '"url": {' + ", ".join(sorted(field)) + "}"


def test_validator_accepts_labelled_field(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    write_valid_plugin(plugin_dir, _plugin_with_schema(_field()))
    assert _mod.validate_plugins([plugin_dir]) == []


def test_validator_rejects_missing_field_label(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    write_valid_plugin(plugin_dir, _plugin_with_schema(_field(label=None)))

    errors = _mod.validate_plugins([plugin_dir])

    assert any("instance_config_schema.url must declare a non-empty label" in e for e in errors)


def test_validator_rejects_title_case_field_label(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    write_valid_plugin(plugin_dir, _plugin_with_schema(_field(label="Server Address")))

    errors = _mod.validate_plugins([plugin_dir])

    assert any("is not in sentence case" in e for e in errors)


def test_validator_allows_proper_nouns_in_field_label(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    write_valid_plugin(plugin_dir, _plugin_with_schema(_field(label="Album ID")))

    assert _mod.validate_plugins([plugin_dir]) == []


def test_validator_rejects_bad_field_description(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    write_valid_plugin(
        plugin_dir,
        _plugin_with_schema(_field(description="Visit https://example.org for more")),
    )
    errors = _mod.validate_plugins([plugin_dir])
    assert any("must not contain a URL" in e for e in errors)
    assert any("must end with a full stop" in e for e in errors)

    plugin_dir = tmp_path / "other-plugin"
    write_valid_plugin(
        plugin_dir,
        _plugin_with_schema(_field(description="x" * (_mod.FIELD_DESCRIPTION_MAX + 1) + ".")),
    )
    errors = _mod.validate_plugins([plugin_dir])
    assert any("longer than" in e for e in errors)


def test_validator_allows_placeholder_example_urls(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    write_valid_plugin(
        plugin_dir,
        _plugin_with_schema(_field(description="For example https://photos.example.com.")),
    )

    assert _mod.validate_plugins([plugin_dir]) == []


def test_validator_rejects_long_plugin_name(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    source = VALID_PLUGIN_PY.replace('name="Demo Plugin"', f'name="{"x" * 29}"')
    write_valid_plugin(plugin_dir, source)

    errors = _mod.validate_plugins([plugin_dir])

    assert any("longer than 28 characters" in e for e in errors)


def test_validator_rejects_plugin_description_with_url(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    source = VALID_PLUGIN_PY.replace("Says demo.", "Read more at https://example.org.")
    write_valid_plugin(plugin_dir, source)

    errors = _mod.validate_plugins([plugin_dir])

    assert any("description must not contain a URL" in e for e in errors)


def test_supported_icons_match_host_map():
    """Mirror of calvin develop PLUGIN_ICON_PATHS (frontend/src/utils/pluginIcon.js).

    An icon the host does not import renders as the name's first letter, so the
    validator must accept exactly the host's curated names.
    """
    assert _mod.SUPPORTED_PLUGIN_ICONS == frozenset(
        {
            "mdi:account",
            "mdi:alert-circle",
            "mdi:bus-clock",
            "mdi:calendar",
            "mdi:camera-outline",
            "mdi:cast",
            "mdi:chart-line",
            "mdi:check",
            "mdi:clock-outline",
            "mdi:cog",
            "mdi:email-outline",
            "mdi:flask-outline",
            "mdi:folder-image",
            "mdi:gauge",
            "mdi:image",
            "mdi:image-auto-adjust",
            "mdi:image-multiple",
            "mdi:lightbulb-outline",
            "mdi:map-marker",
            "mdi:music",
            "mdi:palette",
            "mdi:play-circle",
            "mdi:puzzle",
            "mdi:rss",
            "mdi:server",
            "mdi:shuffle-variant",
            "mdi:silverware-fork-knife",
            "mdi:star",
            "mdi:telescope",
            "mdi:thermometer",
            "mdi:video-outline",
            "mdi:weather-partly-cloudy",
            "mdi:web",
            "mdi:wifi",
        }
    )


def test_validator_accepts_icons_the_host_map_contains(tmp_path):
    for icon in ("mdi:account", "mdi:puzzle", "mdi:thermometer", "mdi:video-outline"):
        plugin_dir = tmp_path / f"demo-{icon.removeprefix('mdi:')}"
        source = VALID_PLUGIN_PY.replace('icon="mdi:flask-outline",', f'icon="{icon}",')
        write_valid_plugin(plugin_dir, source)

        assert _mod.validate_plugins([plugin_dir]) == [], icon


def test_validator_rejects_icons_the_host_map_lacks(tmp_path):
    for icon in ("mdi:home", "mdi:puzzle-outline", "mdi:newspaper", "mdi:video"):
        plugin_dir = tmp_path / f"demo-{icon.removeprefix('mdi:')}"
        source = VALID_PLUGIN_PY.replace('icon="mdi:flask-outline",', f'icon="{icon}",')
        write_valid_plugin(plugin_dir, source)

        errors = _mod.validate_plugins([plugin_dir])
        assert any("not in the host's curated list" in e for e in errors), icon


def test_validator_rejects_unknown_icon(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    source = VALID_PLUGIN_PY.replace("mdi:flask-outline", "mdi:not-in-map")
    write_valid_plugin(plugin_dir, source)

    errors = _mod.validate_plugins([plugin_dir])

    assert any("not in the host's curated list" in e for e in errors)


def test_validator_requires_mdi_icon(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    source = VALID_PLUGIN_PY.replace('icon="mdi:flask-outline",', 'icon="🧪",')
    write_valid_plugin(plugin_dir, source)

    errors = _mod.validate_plugins([plugin_dir])

    assert any("must look like mdi:<name>" in e for e in errors)


def test_validator_rejects_title_case_instance_label(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    source = VALID_PLUGIN_PY.replace('instance_label="source"', 'instance_label="Gallery"')
    write_valid_plugin(plugin_dir, source)

    errors = _mod.validate_plugins([plugin_dir])

    assert any("must be a lowercase noun phrase" in e for e in errors)


def test_published_plugins_exclude_catalog_false():
    manifest = {
        "plugins": [
            {"id": "visible"},
            {"id": "hidden", "catalog": False},
            {"id": "explicit", "catalog": True},
        ]
    }

    assert _mod.published_plugin_ids(manifest) == ["visible", "explicit"]


def test_repository_manifest_marks_test_plugins_non_catalog():
    manifest = _mod.load_repository_manifest()
    flags = {entry["id"]: entry.get("catalog", True) for entry in manifest["plugins"]}

    assert flags["test_plugin"] is False
    assert flags["test_plugin_frontend"] is False
    assert "test_plugin" not in _mod.published_plugin_ids(manifest)


_VALID_THEME = {
    "id": "demo",
    "name": "Demo",
    "version": "1.0.0",
    "theme_api": 2,
    "variables": {
        "bg-0": "#f5f5f5",
        "bg-1": "#ffffff",
        "bg-2": "#ffffff",
        "ink": "#000000",
        "ink-2": "#333333",
        "ink-3": "#555555",
        "line": "#cccccc",
        "line-soft": "#e5e5e5",
        "focus": "#0000ff",
        "ok": "#008000",
        "warn": "#b8860b",
        "err": "#ff0000",
        "shadow": "rgba(0, 0, 0, 0.1)",
        "shadow-hover": "rgba(0, 0, 0, 0.2)",
    },
    "dark_mode": {
        "bg-0": "#000000",
        "bg-1": "#111111",
        "bg-2": "#222222",
        "ink": "#ffffff",
        "ink-2": "#dddddd",
        "ink-3": "#bbbbbb",
        "line": "#333333",
        "line-soft": "#222222",
        "focus": "#8080ff",
        "ok": "#00ff00",
        "warn": "#ffff00",
        "err": "#ff0000",
        "shadow": "rgba(0, 0, 0, 0.5)",
        "shadow-hover": "rgba(0, 0, 0, 0.6)",
    },
}


def _write_theme(tmp_path: Path, **overrides) -> Path:
    theme = json.loads(json.dumps(_VALID_THEME))
    theme.update(overrides)
    path = tmp_path / "theme.json"
    path.write_text(json.dumps(theme), encoding="utf-8")
    return path


def test_theme_validator_accepts_valid_theme(tmp_path):
    assert _mod.validate_theme(_write_theme(tmp_path)) == []


def test_theme_validator_requires_theme_api_2(tmp_path):
    path = _write_theme(tmp_path)
    theme = json.loads(path.read_text(encoding="utf-8"))
    del theme["theme_api"]
    path.write_text(json.dumps(theme), encoding="utf-8")

    errors = _mod.validate_theme(path)

    assert any("theme_api must be 2" in error for error in errors)


def test_theme_validator_names_missing_base_colour(tmp_path):
    theme = json.loads(json.dumps(_VALID_THEME))
    del theme["dark_mode"]["bg-2"]

    errors = _mod.validate_theme(_write_theme(tmp_path, **theme))

    assert any("missing bg-2 in dark_mode" in error for error in errors)


def test_theme_validator_rejects_non_colour_keys(tmp_path):
    theme = json.loads(json.dumps(_VALID_THEME))
    theme["variables"]["bg-primary"] = "#000000"

    errors = _mod.validate_theme(_write_theme(tmp_path, **theme))

    assert any("variables.bg-primary is not a colour token" in error for error in errors)


def test_theme_validator_rejects_bad_colour_value(tmp_path):
    theme = json.loads(json.dumps(_VALID_THEME))
    theme["variables"]["focus"] = "url(https://example.org/x)"

    errors = _mod.validate_theme(_write_theme(tmp_path, **theme))

    assert any("variables.focus is not a valid colour" in error for error in errors)


def test_theme_validator_rejects_low_contrast(tmp_path):
    theme = json.loads(json.dumps(_VALID_THEME))
    theme["variables"]["ink-3"] = "#eeeeee"

    errors = _mod.validate_theme(_write_theme(tmp_path, **theme))

    assert any("ink-3 is below AA on bg-1 in variables" in error for error in errors)


def test_theme_validator_rejects_colliding_status_hues(tmp_path):
    theme = json.loads(json.dumps(_VALID_THEME))
    theme["variables"]["ok"] = theme["variables"]["focus"]

    errors = _mod.validate_theme(_write_theme(tmp_path, **theme))

    assert any("focus and ok" in error for error in errors)


def test_owned_plugins_and_theme_pass_repository_rules():
    assert _mod.validate_themes() == []
    assert _mod.validate_repository_manifest() == []


ICON_MAP_RELPATH = Path("frontend/src/utils/pluginIcon.js")


def _find_calvin_dir():
    env = os.environ.get("CALVIN_DIR")
    if env:
        return Path(env)
    # CI layout: calvin-plugins and calvin are siblings in $GITHUB_WORKSPACE.
    return Path(__file__).resolve().parent.parent / "calvin"


def _host_icon_names(source):
    match = re.search(r"PLUGIN_ICON_PATHS\s*=\s*Object\.freeze\(\{(.*?)\}\)", source, re.S)
    assert match, "PLUGIN_ICON_PATHS = Object.freeze({...}) not found in pluginIcon.js"
    names = set()
    for line in match.group(1).splitlines():
        key = re.match(r"""\s*(?:"([^"]+)"|'([^']+)'|([A-Za-z_$][\w$]*))\s*:""", line)
        if key:
            names.add("mdi:" + (key.group(1) or key.group(2) or key.group(3)))
    return names


def test_icon_list_matches_host_icon_map():
    """The validator's icon list must equal the keys of the host's PLUGIN_ICON_PATHS."""
    icon_file = _find_calvin_dir() / ICON_MAP_RELPATH
    if not icon_file.is_file():
        if os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("CI"):
            pytest.fail(
                f"CI must enforce the icon-map guard but {icon_file} does not exist; "
                "check that the calvin checkout (CALVIN_REF in .github/workflows/ci.yml) "
                f"contains {ICON_MAP_RELPATH}"
            )
        pytest.skip(
            f"no calvin checkout with {ICON_MAP_RELPATH} (set CALVIN_DIR or place it at "
            "../calvin); outside CI this is skipped"
        )
    host = _host_icon_names(icon_file.read_text(encoding="utf-8"))
    assert host, "parsed no keys from PLUGIN_ICON_PATHS"
    mirror = set(_mod.SUPPORTED_PLUGIN_ICONS)
    assert mirror == host, (
        "SUPPORTED_PLUGIN_ICONS in scripts/validate_plugins.py has drifted from the host's "
        f"PLUGIN_ICON_PATHS ({icon_file}). "
        f"Missing from the validator: {sorted(host - mirror)}. "
        f"Missing from the host: {sorted(mirror - host)}."
    )
