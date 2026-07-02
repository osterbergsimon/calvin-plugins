"""Tests for the Image Processor plugin (plugin contract 1.0).

Run from the calvin backend directory so `app.*` imports resolve:
    cd calvin/backend
    uv run pytest ../../calvin-plugins/image-processor/test_image_processor.py
"""

import importlib.util
import tempfile
import types
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

try:
    from app.plugins.definitions import PluginMetadata
    from app.plugins.loader import PluginLoader
    from app.plugins.protocols import BackendPlugin
except ImportError as e:  # pragma: no cover
    pytest.skip(f"Backend dependencies not available: {e}", allow_module_level=True)


def _load_plugin_module():
    plugin_path = Path(__file__).parent / "plugin.py"
    spec = importlib.util.spec_from_file_location(
        "image_processor_plugin_under_test", plugin_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


image_processor_module = _load_plugin_module()
ImageProcessorPlugin = image_processor_module.ImageProcessorPlugin


@pytest.fixture
def plugin():
    """A plugin instance with default (empty) config."""
    return ImageProcessorPlugin(
        plugin_id="image-processor-test", name="Image Processor", enabled=True
    )


class TestContractShape:
    """The plugin conforms to contract 1.0: one class, declarative metadata."""

    def test_discoverable_by_loader(self):
        loader = PluginLoader()
        module = types.ModuleType("installed_plugin_image_processor")
        module.ImageProcessorPlugin = ImageProcessorPlugin
        assert loader.register_module(module) == ["image-processor"]

    def test_no_module_level_hooks(self):
        for hook in (
            "register_plugin_types",
            "create_plugin_instance",
            "handle_plugin_config_update",
        ):
            assert not hasattr(image_processor_module, hook), hook

    def test_metadata(self):
        md = ImageProcessorPlugin.metadata
        assert isinstance(md, PluginMetadata)
        assert md.type_id == "image-processor"
        assert md.supports_multiple_instances is True
        assert md.instance_label == "Processor"
        assert md.instance_identity == ["max_width", "max_height", "thumbnail_size"]
        assert md.display_schema is None  # backend plugin: no panel
        for key in (
            "processing_enabled",
            "resize_enabled",
            "max_width",
            "max_height",
            "generate_thumbnails",
            "thumbnail_size",
        ):
            assert key in md.instance_config_schema, key

    def test_is_backend_plugin(self):
        assert issubclass(ImageProcessorPlugin, BackendPlugin)


class TestConfig:
    async def test_configure_normalizes_via_schema(self, plugin):
        await plugin.configure(
            {
                "processing_enabled": "true",
                "max_width": "2560",
                "max_height": 1440,
                "thumbnail_size": "400",
            }
        )
        config = plugin.get_config()
        assert config["processing_enabled"] is True
        assert config["max_width"] == 2560
        assert config["max_height"] == 1440
        assert config["thumbnail_size"] == 400
        assert config["generate_thumbnails"] is True  # schema default

    async def test_validate_config(self):
        assert await ImageProcessorPlugin.validate_config({}) is True  # defaults are valid
        assert await ImageProcessorPlugin.validate_config(
            {"max_width": 1000, "max_height": 800, "thumbnail_size": 200}
        ) is True
        assert await ImageProcessorPlugin.validate_config({"max_width": 0}) is False
        assert await ImageProcessorPlugin.validate_config({"max_width": -1}) is False
        assert await ImageProcessorPlugin.validate_config({"max_height": 0}) is False
        assert await ImageProcessorPlugin.validate_config(
            {"generate_thumbnails": True, "thumbnail_size": 0}
        ) is False
        # Thumbnail size is irrelevant when thumbnails are disabled
        assert await ImageProcessorPlugin.validate_config(
            {"generate_thumbnails": False, "thumbnail_size": 0}
        ) is True

    def test_instance_identity_stable_per_settings(self):
        config = {"max_width": 1920, "max_height": 1080, "thumbnail_size": 300}
        assert ImageProcessorPlugin.instance_id_for(config) == ImageProcessorPlugin.instance_id_for(
            {**config, "processing_enabled": False}
        )
        assert ImageProcessorPlugin.instance_id_for(config) != ImageProcessorPlugin.instance_id_for(
            {**config, "thumbnail_size": 400}
        )


class TestEventSubscription:
    async def test_subscribes_when_enabled(self, plugin):
        await plugin.configure({"processing_enabled": True})
        assert await plugin.get_subscribed_events() == ["image_uploaded"]

    async def test_no_subscription_when_plugin_disabled(self, plugin):
        plugin.disable()
        assert await plugin.get_subscribed_events() == []

    async def test_no_subscription_when_processing_disabled(self, plugin):
        await plugin.configure({"processing_enabled": False})
        assert await plugin.get_subscribed_events() == []


class TestEventHandling:
    """Event-driven behavior is preserved exactly."""

    async def test_unknown_event_ignored(self, plugin):
        assert await plugin.handle_event("plugin_enabled", {}) is None

    async def test_image_uploaded_processed(self, plugin):
        await plugin.configure(
            {
                "processing_enabled": True,
                "resize_enabled": True,
                "max_width": 1920,
                "max_height": 1080,
                "generate_thumbnails": True,
                "thumbnail_size": 300,
            }
        )
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_file:
            tmp_file.write(b"fake image data")
            tmp_path = tmp_file.name

        try:
            event_data = {
                "image_id": "test-image-1",
                "filename": "test.jpg",
                "path": tmp_path,
                "plugin_id": "source-plugin",
            }
            with patch.object(plugin, "emit_event", new_callable=AsyncMock) as mock_emit:
                result = await plugin.handle_event("image_uploaded", event_data)

            assert result["success"] is True
            assert "Processed test.jpg" in result["message"]
            assert result["processing_results"]["resized"] is True
            assert result["processing_results"]["max_dimensions"] == {
                "width": 1920,
                "height": 1080,
            }
            assert result["processing_results"]["thumbnail_generated"] is True
            assert result["processing_results"]["thumbnail_size"] == 300
            assert plugin._processed_count == 1
            assert plugin._error_count == 0

            mock_emit.assert_called_once()
            assert mock_emit.call_args[0][0] == "image_processed"
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    async def test_image_uploaded_without_resize_or_thumbnails(self, plugin):
        await plugin.configure(
            {
                "processing_enabled": True,
                "resize_enabled": False,
                "generate_thumbnails": False,
            }
        )
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_file:
            tmp_file.write(b"fake image data")
            tmp_path = tmp_file.name

        try:
            event_data = {
                "image_id": "test-image-1",
                "filename": "test.jpg",
                "path": tmp_path,
                "plugin_id": "source-plugin",
            }
            with patch.object(plugin, "emit_event", new_callable=AsyncMock):
                result = await plugin.handle_event("image_uploaded", event_data)

            assert result["success"] is True
            assert "resized" not in result["processing_results"]
            assert "thumbnail_generated" not in result["processing_results"]
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    async def test_image_uploaded_missing_file(self, plugin):
        result = await plugin.handle_event(
            "image_uploaded",
            {
                "image_id": "test-image-1",
                "filename": "nonexistent.jpg",
                "path": "/nonexistent/path/image.jpg",
                "plugin_id": "source-plugin",
            },
        )
        assert result["success"] is False
        assert "Image path not found" in result["error"]
        assert plugin._processed_count == 0
        assert plugin._error_count == 1

    async def test_image_uploaded_processing_error(self, plugin):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_file:
            tmp_file.write(b"fake image data")
            tmp_path = tmp_file.name

        try:
            event_data = {
                "image_id": "test-image-1",
                "filename": "test.jpg",
                "path": tmp_path,
                "plugin_id": "source-plugin",
            }
            with (
                patch.object(plugin, "get_config", side_effect=Exception("Test error")),
                patch.object(plugin, "emit_event", new_callable=AsyncMock) as mock_emit,
            ):
                result = await plugin.handle_event("image_uploaded", event_data)

            assert result["success"] is False
            assert "Test error" in result["error"]
            assert plugin._error_count == 1
            mock_emit.assert_called_once()
            assert mock_emit.call_args[0][0] == "image_processing_failed"
        finally:
            Path(tmp_path).unlink(missing_ok=True)


class TestServiceProvider:
    async def test_get_processing_stats(self, plugin):
        plugin._processed_count = 10
        plugin._error_count = 2
        stats = await plugin.get_processing_stats()
        assert stats == {"processed_count": 10, "error_count": 2, "total_processed": 12}

    async def test_provide_service(self, plugin):
        plugin._processed_count = 5
        plugin._error_count = 1
        stats = await plugin.provide_service("get_processing_stats")
        assert stats["processed_count"] == 5
        assert stats["error_count"] == 1
        assert await plugin.provide_service("non_existent_service") is None

    async def test_get_provided_services(self, plugin):
        assert await plugin.get_provided_services() == ["get_processing_stats"]
