"""Tests for plugin metadata validation (contract 1.0)."""

import json
from pathlib import Path

from conftest import load_script

_mod = load_script("validate_plugins")

VALID_PLUGIN_PY = """
from app.plugins.definitions import PluginMetadata
from app.plugins.protocols import ServicePlugin


class DemoServicePlugin(ServicePlugin):
    metadata = PluginMetadata(
        type_id="demo_plugin",
        name="Demo Plugin",
        instance_label="Source",
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
        instance_label="Source",
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


def test_validator_rejects_non_literal_browser_origin(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    src = _PY_WITH_BROWSER_ORIGINS % "SOME_VAR"
    write_valid_plugin(plugin_dir, src)
    errors = _mod.validate_plugins([plugin_dir])
    assert any("browser_origins" in error for error in errors)
