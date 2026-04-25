"""Tests for plugin metadata validation."""

import importlib.util
import sys
from pathlib import Path


_spec = importlib.util.spec_from_file_location(
    "validate_plugins", Path(__file__).parent / "scripts" / "validate_plugins.py"
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)


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
