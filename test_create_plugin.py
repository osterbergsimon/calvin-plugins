"""Tests for plugin scaffolding."""

import argparse
import importlib.util
from pathlib import Path


_spec = importlib.util.spec_from_file_location(
    "create_plugin", Path(__file__).parent / "scripts" / "create_plugin.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
create_plugin = _mod.create_plugin
generate_plugin_json = _mod.generate_plugin_json


def test_generated_manifest_includes_protocol_version():
    manifest_json = generate_plugin_json("demo-service", "Demo Service", "service", "Demo", "")

    assert '"format_version": "1.0.0"' in manifest_json
    assert '"protocol_version": 1' in manifest_json


def test_generated_manifest_includes_protocol_version_for_all_types():
    for plugin_type in ("service", "image", "calendar", "backend"):
        manifest_json = generate_plugin_json("demo-plugin", "Demo Plugin", plugin_type, "Demo", "")
        assert '"protocol_version": 1' in manifest_json


def test_create_plugin_writes_protocol_version(tmp_path, monkeypatch):
    monkeypatch.setattr(_mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(_mod.subprocess, "run", lambda *args, **kwargs: None)

    args = argparse.Namespace(
        type="image",
        id="demo-gallery",
        name="Demo Gallery",
        description="Demo gallery plugin.",
        single=True,
        label="Gallery",
        author="",
        no_tests=False,
    )

    result = create_plugin(args)

    plugin_dir = tmp_path / "demo-gallery"

    assert result == 0
    assert plugin_dir.exists()
    assert (plugin_dir / "plugin.json").exists()
    assert (plugin_dir / "test_demo_gallery.py").exists()
    assert '"protocol_version": 1' in (plugin_dir / "plugin.json").read_text(encoding="utf-8")
