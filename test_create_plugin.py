"""Tests for plugin scaffolding (contract 1.0)."""

import argparse

from conftest import load_script

_mod = load_script("create_plugin")
create_plugin = _mod.create_plugin
generate_plugin_json = _mod.generate_plugin_json
generate_plugin_py = _mod.generate_plugin_py

_validator_mod = load_script("validate_plugins")


def _args(**overrides):
    defaults = dict(
        type="service",
        id="demo-service",
        name="Demo Service",
        description="Demo service plugin.",
        single=False,
        label=None,
        author="",
        no_tests=False,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_scaffold_is_declarative():
    """The scaffold emits one class + PluginMetadata — no hooks, no SDK builders."""
    for plugin_type in ("service", "image", "calendar", "backend"):
        plugin_py = generate_plugin_py("demo-x", "Demo X", plugin_type, "Demo", False, "Thing")
        assert "metadata = PluginMetadata(" in plugin_py
        assert "from app.plugins.definitions import PluginMetadata" in plugin_py
        for retired in (
            "hookimpl",
            "register_plugin_types",
            "create_plugin_instance",
            "handle_plugin_config_update",
            "get_plugin_metadata",
            "app.plugins.sdk",
            "ConfigField",
        ):
            assert retired not in plugin_py, f"{plugin_type} scaffold contains {retired}"


def test_service_scaffold_has_fetch_and_display_schema():
    plugin_py = generate_plugin_py("demo-service", "Demo Service", "service", "Demo", False, None)
    assert "async def fetch(" in plugin_py
    assert '"kind": "status"' in plugin_py
    assert "get_content" not in plugin_py


def test_calendar_scaffold_uses_real_protocol_signature():
    plugin_py = generate_plugin_py("demo-cal", "Demo Cal", "calendar", "Demo", False, "Calendar")
    assert "async def fetch_events(" in plugin_py
    assert "start_date: datetime" in plugin_py
    assert "CalendarEvent" in plugin_py


def test_single_instance_scaffold_declares_fixed_id():
    plugin_py = generate_plugin_py("demo-image", "Demo Image", "image", "Demo", True, "Gallery")
    assert "supports_multiple_instances=False" in plugin_py
    assert 'fixed_instance_id="demo_image-instance"' in plugin_py


def test_multi_instance_scaffold_includes_default_instance_label(tmp_path, monkeypatch):
    monkeypatch.setattr(_mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(_mod.subprocess, "run", lambda *args, **kwargs: None)

    result = create_plugin(_args())

    plugin_dir = tmp_path / "demo-service"
    plugin_py = (plugin_dir / "plugin.py").read_text(encoding="utf-8")

    assert result == 0
    assert 'instance_label="Service"' in plugin_py
    assert _validator_mod.validate_plugins([plugin_dir]) == []


def test_generated_manifest_declares_api_version():
    for plugin_type in ("service", "image", "calendar", "backend"):
        manifest_json = generate_plugin_json("demo-plugin", "Demo Plugin", plugin_type, "Demo", "")
        assert '"api_version": 1' in manifest_json
        assert "format_version" not in manifest_json
        assert "protocol_version" not in manifest_json


def test_create_plugin_writes_declarative_scaffold(tmp_path, monkeypatch):
    monkeypatch.setattr(_mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(_mod.subprocess, "run", lambda *args, **kwargs: None)

    result = create_plugin(
        _args(type="image", id="demo-gallery", name="Demo Gallery", single=True, label="Gallery")
    )

    plugin_dir = tmp_path / "demo-gallery"
    plugin_py = (plugin_dir / "plugin.py").read_text(encoding="utf-8")

    assert result == 0
    assert plugin_dir.exists()
    assert (plugin_dir / "plugin.json").exists()
    assert (plugin_dir / "test_demo_gallery.py").exists()
    assert '"api_version": 1' in (plugin_dir / "plugin.json").read_text(encoding="utf-8")
    assert "metadata = PluginMetadata(" in plugin_py
    assert 'fixed_instance_id="demo_gallery-instance"' in plugin_py
    assert _validator_mod.validate_plugins([plugin_dir]) == []


def test_create_plugin_prints_validator_next_step(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(_mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(_mod.subprocess, "run", lambda *args, **kwargs: None)

    result = create_plugin(
        _args(type="backend", id="demo-worker", name="Demo Worker", no_tests=True)
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "python scripts/validate_plugins.py demo-worker" in captured.out
