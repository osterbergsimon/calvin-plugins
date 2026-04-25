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
generate_plugin_py = _mod.generate_plugin_py


def test_service_scaffold_uses_service_sdk():
    plugin_py = generate_plugin_py("demo-service", "Demo Service", "service", "Demo", False, None)

    assert "from app.plugins.sdk.service import (" in plugin_py
    assert "ServiceConfigField" in plugin_py
    assert "build_service_plugin_metadata(" in plugin_py
    assert "create_service_plugin_instance(" in plugin_py
    assert "build_service_manager_config(" in plugin_py


def test_image_scaffold_uses_image_sdk():
    plugin_py = generate_plugin_py("demo-image", "Demo Image", "image", "Demo", True, "Gallery")

    assert "from app.plugins.sdk.image import (" in plugin_py
    assert "ImageConfigField" in plugin_py
    assert "build_image_plugin_metadata(" in plugin_py
    assert 'instance_label="Gallery"' in plugin_py
    assert 'expected_type_id="demo_image"' in plugin_py
    assert 'instance_id="demo_image-instance"' in plugin_py


def test_calendar_scaffold_uses_calendar_sdk():
    plugin_py = generate_plugin_py(
        "demo-calendar", "Demo Calendar", "calendar", "Demo", False, "Calendar"
    )

    assert "from app.plugins.sdk.calendar import (" in plugin_py
    assert "CalendarConfigField" in plugin_py
    assert "build_calendar_plugin_metadata(" in plugin_py
    assert 'expected_type_ids="demo_calendar"' in plugin_py
    assert "build_calendar_manager_config(" in plugin_py


def test_backend_scaffold_uses_backend_sdk():
    plugin_py = generate_plugin_py("demo-backend", "Demo Backend", "backend", "Demo", False, None)

    assert "from app.plugins.sdk.backend import (" in plugin_py
    assert "BackendConfigField" in plugin_py
    assert "build_backend_plugin_metadata(" in plugin_py
    assert "create_backend_plugin_instance(" in plugin_py
    assert "build_backend_manager_config(" in plugin_py


def test_create_plugin_writes_sdk_first_scaffold(tmp_path, monkeypatch):
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
    plugin_py = (plugin_dir / "plugin.py").read_text(encoding="utf-8")

    assert result == 0
    assert plugin_dir.exists()
    assert (plugin_dir / "plugin.json").exists()
    assert (plugin_dir / "test_demo_gallery.py").exists()
    assert "from app.plugins.sdk.image import (" in plugin_py
    assert 'instance_id="demo_gallery-instance"' in plugin_py
