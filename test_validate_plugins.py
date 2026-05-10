"""Tests for plugin metadata validation."""

import json
from pathlib import Path

from conftest import load_script

_mod = load_script("validate_plugins")


def test_owned_plugins_pass_metadata_validation():
    assert _mod.validate_plugins() == []


def test_validator_rejects_reserved_schema_field(tmp_path):
    plugin_py = tmp_path / "plugin.py"
    plugin_py.write_text(
        """
from app.plugins.base import PluginType

def metadata():
    return {
        "type_id": "bad_plugin",
        "plugin_type": PluginType.SERVICE,
        "name": "Bad Plugin",
        "instance_label": "Source",
        "common_config_schema": {
            "display_order": {"type": "integer"},
        },
        "instance_config_schema": {},
    }
""",
        encoding="utf-8",
    )

    errors = _mod.validate_plugins([plugin_py])

    assert any("common_config_schema.display_order is app-managed" in error for error in errors)


def write_valid_plugin(plugin_dir: Path) -> Path:
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "id": "demo_plugin",
                "name": "Demo Plugin",
                "version": "1.0.0",
                "type": "service",
                "format_version": "1.0.0",
                "protocol_version": 1,
            }
        ),
        encoding="utf-8",
    )
    plugin_py = plugin_dir / "plugin.py"
    plugin_py.write_text(
        """
from app.plugins.base import PluginType

def metadata():
    return {
        "type_id": "demo_plugin",
        "plugin_type": PluginType.SERVICE,
        "name": "Demo Plugin",
        "instance_label": "Source",
        "common_config_schema": {},
        "instance_config_schema": {},
    }
""",
        encoding="utf-8",
    )
    return plugin_py


def test_validator_accepts_explicit_plugin_directory(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    write_valid_plugin(plugin_dir)

    assert _mod.validate_plugins([plugin_dir]) == []


def test_validator_accepts_explicit_plugin_py(tmp_path):
    plugin_py = write_valid_plugin(tmp_path / "demo-plugin")

    assert _mod.validate_plugins([plugin_py]) == []


def test_validator_rejects_missing_manifest_for_explicit_directory(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.py").write_text("def metadata():\n    return {}\n", encoding="utf-8")

    errors = _mod.validate_plugins([plugin_dir])

    assert any("plugin.json: file does not exist" in error for error in errors)


def test_validator_rejects_invalid_manifest_type(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    write_valid_plugin(plugin_dir)
    manifest_path = plugin_dir / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["type"] = "dashboard"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    errors = _mod.validate_plugins([plugin_dir])

    assert any("invalid type 'dashboard'" in error for error in errors)


def test_validator_rejects_manifest_metadata_id_mismatch(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    write_valid_plugin(plugin_dir)
    manifest_path = plugin_dir / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["id"] = "other_plugin"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    errors = _mod.validate_plugins([plugin_dir])

    assert any("metadata type_id 'demo_plugin' does not match" in error for error in errors)


def test_validator_rejects_manifest_metadata_type_mismatch(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    write_valid_plugin(plugin_dir)
    manifest_path = plugin_dir / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["type"] = "image"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    errors = _mod.validate_plugins([plugin_dir])

    assert any("metadata plugin_type 'service' does not match" in error for error in errors)


def test_validator_rejects_missing_plugin_py_for_explicit_directory(tmp_path):
    plugin_dir = tmp_path / "demo-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "id": "demo_plugin",
                "name": "Demo Plugin",
                "version": "1.0.0",
                "type": "service",
            }
        ),
        encoding="utf-8",
    )

    errors = _mod.validate_plugins([plugin_dir])

    assert any("plugin.py not found" in error for error in errors)


def test_validator_rejects_unscoped_action(tmp_path):
    plugin_py = tmp_path / "plugin.py"
    plugin_py.write_text(
        """
from app.plugins.base import PluginType

def metadata():
    return {
        "type_id": "bad_plugin",
        "plugin_type": PluginType.SERVICE,
        "name": "Bad Plugin",
        "instance_label": "Source",
        "common_config_schema": {},
        "instance_config_schema": {},
        "ui_actions": [
            {"id": "test", "type": "test", "label": "Test"},
        ],
    }
""",
        encoding="utf-8",
    )

    errors = _mod.validate_plugins([plugin_py])

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
